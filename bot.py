import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from dotenv import load_dotenv


load_dotenv(override=True)

DATA_DIR = Path("data")
STORE_PATH = DATA_DIR / "store.json"
REWARD_PATH = DATA_DIR / "rewards.json"


def env_int(name: str, default: int = 0) -> int:
    val = os.getenv(name) or os.getenv(name.lower())
    return int(val) if val and val.isdigit() else default


def env_str(name: str, default: str) -> str:
    return os.getenv(name) or os.getenv(name.lower()) or default


def env_secret(name: str) -> str:
    return env_str(name, "").strip().strip('"').strip("'")


@dataclass(frozen=True)
class TicketCategory:
    key: str
    label: str
    channel_id: int


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int
    ticket_categories: tuple[TicketCategory, ...]
    support_role_id: int
    moderator_role_id: int
    admin_role_id: int
    log_channel_id: int
    quota_points: int
    points_per_claim: int
    prefix: str


cfg = Config(
    token=env_secret("DISCORD_TOKEN"),
    guild_id=env_int("GUILD_ID"),
    ticket_categories=(
        TicketCategory("first", env_str("FIRST_CATEGORY_NAME", "Support Tickets"), env_int("FIRST_CATEGORY_ID")),
        TicketCategory("second", env_str("SECOND_CATEGORY_NAME", "Ban Appeals"), env_int("SECOND_CATEGORY_ID")),
        TicketCategory("third", env_str("THIRD_CATEGORY_NAME", "Donation Tickets"), env_int("THIRD_CATEGORY_ID")),
        TicketCategory("fourth", env_str("FOURTH_CATEGORY_NAME", "Partner Tickets"), env_int("FOURTH_CATEGORY_ID")),
        TicketCategory("fifth", env_str("FIFTH_CATEGORY_NAME", "Other Tickets"), env_int("FIFTH_CATEGORY_ID")),
    ),
    support_role_id=env_int("SUPPORT_ROLE_ID"),
    moderator_role_id=env_int("MODERATOR_ROLE_ID"),
    admin_role_id=env_int("ADMIN_ROLE_ID"),
    log_channel_id=env_int("LOG_CHANNEL_ID"),
    quota_points=env_int("QUOTA_POINTS", 25),
    points_per_claim=env_int("POINTS_PER_CLAIM", 1),
    prefix=os.getenv("COMMAND_PREFIX", "!"),
)

if not cfg.token:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")

print(f"Using DISCORD_TOKEN={cfg.token[:8]}...{cfg.token[-6:]} len={len(cfg.token)}")


class JsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = asyncio.Lock()
        self.data: dict[str, Any] = {"users": {}, "tickets": {}, "period_started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "biweekly_goal": cfg.quota_points}

    async def load(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        if self.path.exists():
            self.data = json.loads(self.path.read_text("utf-8"))
        self.data.setdefault("users", {})
        self.data.setdefault("tickets", {})
        self.data.setdefault("period_started", utc_now())
        self.data.setdefault("biweekly_goal", cfg.quota_points)
        for user in self.data["users"].values():
            self.patch_user(user)
        await self.save()

    async def save(self) -> None:
        async with self.lock:
            self.path.write_text(json.dumps(self.data, indent=2), "utf-8")

    def user(self, uid: int) -> dict[str, Any]:
        user = self.data.setdefault("users", {}).setdefault(str(uid), {})
        return self.patch_user(user)

    @staticmethod
    def patch_user(user: dict[str, Any]) -> dict[str, Any]:
        user.setdefault("points", 0)
        user.setdefault("claims", 0)
        user.setdefault("lifetime_tickets", int(user.get("claims", 0)))
        user.setdefault("biweekly_tickets", 0)
        return user

    async def add_points(self, uid: int, points: int) -> int:
        user = self.user(uid)
        user["points"] = max(0, int(user.get("points", 0)) + points)
        await self.save()
        return user["points"]

    async def add_claim(self, uid: int) -> int:
        user = self.user(uid)
        user["claims"] = int(user.get("claims", 0)) + 1
        user["points"] = int(user.get("points", 0)) + cfg.points_per_claim
        await self.save()
        return user["points"]

    async def add_closed_ticket(self, uid: int) -> dict[str, Any]:
        user = self.user(uid)
        user["claims"] = int(user["claims"]) + 1
        user["points"] = int(user["points"]) + cfg.points_per_claim
        user["lifetime_tickets"] = int(user["lifetime_tickets"]) + 1
        user["biweekly_tickets"] = int(user["biweekly_tickets"]) + 1
        await self.save()
        return user

    async def reset_biweekly(self, goal: int | None = None) -> None:
        self.data["period_started"] = utc_now()
        if goal is not None:
            self.data["biweekly_goal"] = max(1, int(goal))
        for user in self.data.setdefault("users", {}).values():
            self.patch_user(user)["biweekly_tickets"] = 0
        await self.save()


store = JsonStore(STORE_PATH)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def period_started() -> datetime:
    raw = str(store.data.get("period_started") or utc_now())
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def period_age() -> str:
    days = max(0, (datetime.now(timezone.utc) - period_started()).days)
    return f"{days} day{'s' if days != 1 else ''} ago"


def biweekly_goal() -> int:
    return max(1, int(store.data.get("biweekly_goal", cfg.quota_points)))


def progress_bar(done: int, goal: int, size: int = 10) -> str:
    filled = min(size, round((done / max(goal, 1)) * size))
    return "█" * filled + "░" * (size - filled)


def slug(name: str) -> str:
    clean = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return clean[:32] or "user"


def ticket_category(key: str) -> TicketCategory | None:
    return next((c for c in cfg.ticket_categories if c.key == key), None)


def ticket_category_key(channel: discord.TextChannel) -> str:
    return next((c.key for c in cfg.ticket_categories if c.channel_id and c.channel_id == channel.category_id), "external")


def ticket_channel_id(record: Any) -> str:
    return str(record.get("channel_id")) if isinstance(record, dict) else str(record)


def is_ticket_channel(channel: discord.TextChannel) -> bool:
    cat_ids = {c.channel_id for c in cfg.ticket_categories if c.channel_id}
    return channel.name.lower().startswith("ticket-") or bool(channel.category_id and channel.category_id in cat_ids)


def ticket_by_channel(channel: discord.TextChannel) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    for key, record in store.data.get("tickets", {}).items():
        if ticket_channel_id(record) == str(channel.id):
            if not isinstance(record, dict):
                record = {"channel_id": str(record), "claimed_by": None}
                store.data["tickets"][key] = record
            return key, record
    if is_ticket_channel(channel):
        key = f"external:{channel.id}"
        record = {
            "channel_id": str(channel.id),
            "owner_id": None,
            "category": ticket_category_key(channel),
            "claimed_by": None,
            "created_at": utc_now(),
        }
        store.data.setdefault("tickets", {})[key] = record
        return key, record
    return None, None


def embed(title: str, description: str, color: int = 0x2F3136) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    e.set_footer(text="Ticket Bot")
    return e


def ticket_stats_embed(member: discord.User | discord.Member, data: dict[str, Any]) -> discord.Embed:
    lifetime = int(data.get("lifetime_tickets", 0))
    biweekly = int(data.get("biweekly_tickets", 0))
    points = int(data.get("points", 0))
    goal = biweekly_goal()
    e = discord.Embed(
        title=f"Ticket Stats - {member.display_name}",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    e.add_field(name="Lifetime Tickets", value=f"`{lifetime}`", inline=True)
    e.add_field(name="Biweekly Tickets", value=f"`{biweekly}` / `{goal}`", inline=True)
    e.add_field(name="Points", value=f"`{points}`", inline=False)
    e.add_field(name="Period Started", value=period_age(), inline=False)
    e.description = "Tickets are awarded when a staff member closes a ticket."
    e.set_thumbnail(url=member.display_avatar.url)
    return e


async def member_name(guild: discord.Guild, uid: str) -> str:
    member = guild.get_member(int(uid))
    if not member:
        try:
            member = await guild.fetch_member(int(uid))
        except discord.HTTPException:
            return f"<@{uid}>"
    return member.display_name


async def log(guild: discord.Guild, title: str, desc: str, color: int = 0x5865F2) -> None:
    ch = guild.get_channel(cfg.log_channel_id)
    if isinstance(ch, discord.TextChannel):
        await ch.send(embed=embed(title, desc, color))


def has_role(member: discord.Member, role_id: int) -> bool:
    return bool(role_id) and any(r.id == role_id for r in member.roles)


def is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or has_role(member, cfg.admin_role_id)


def is_moderator(member: discord.Member) -> bool:
    return is_admin(member) or has_role(member, cfg.moderator_role_id)


def is_support(member: discord.Member) -> bool:
    return is_moderator(member) or has_role(member, cfg.support_role_id)


def is_support_only(member: discord.Member) -> bool:
    return has_role(member, cfg.support_role_id) and not is_moderator(member)


def can_manage_ticket(member: discord.Member, ticket: dict[str, Any]) -> bool:
    category = ticket.get("category")
    if is_admin(member):
        return True
    if has_role(member, cfg.moderator_role_id):
        return category in {"first", "third"}
    return has_role(member, cfg.support_role_id) and category == "first"


def can_manage_points(member: discord.Member) -> bool:
    return is_admin(member)


async def reply(inter: discord.Interaction, *, embed: discord.Embed, ephemeral: bool = False) -> None:
    if inter.response.is_done():
        await inter.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        await inter.response.send_message(embed=embed, ephemeral=ephemeral)


async def require_staff(inter: discord.Interaction) -> bool:
    if isinstance(inter.user, discord.Member) and is_support(inter.user):
        return True
    await reply(inter, embed=embed("Missing permissions", "This command is staff-only.", 0xED4245), ephemeral=True)
    return False


async def require_admin(inter: discord.Interaction) -> bool:
    if isinstance(inter.user, discord.Member) and can_manage_points(inter.user):
        return True
    await reply(inter, embed=embed("Missing permissions", "This command is admin-only.", 0xED4245), ephemeral=True)
    return False


async def require_ticket_manager(inter: discord.Interaction, ticket: dict[str, Any]) -> bool:
    if isinstance(inter.user, discord.Member) and can_manage_ticket(inter.user, ticket):
        return True
    await reply(inter, embed=embed("Missing permissions", "You cannot manage this ticket category.", 0xED4245), ephemeral=True)
    return False


def load_rewards() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(exist_ok=True)
    if not REWARD_PATH.exists():
        REWARD_PATH.write_text(
            json.dumps(
                [
                    {"id": "vip", "name": "VIP", "cost": 50},
                    {"id": "role", "name": "Rola eventowa", "cost": 100},
                    {"id": "custom", "name": "Custom nagroda", "cost": 250},
                ],
                indent=2,
            ),
            "utf-8",
        )
    return json.loads(REWARD_PATH.read_text("utf-8"))


class TicketView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        for cat in cfg.ticket_categories:
            btn = discord.ui.Button(label=cat.label, style=discord.ButtonStyle.green, custom_id=f"ticket:create:{cat.key}")
            btn.callback = self.create_ticket
            self.add_item(btn)

    async def create_ticket(self, inter: discord.Interaction) -> None:
        if not inter.guild or not isinstance(inter.user, discord.Member):
            return
        cat_key = str(inter.data.get("custom_id", "")).rsplit(":", 1)[-1] if inter.data else ""
        ticket_cat = ticket_category(cat_key)
        if not ticket_cat or not ticket_cat.channel_id:
            await inter.response.send_message(embed=embed("Missing configuration", "This category has no ID configured in `.env`.", 0xED4245), ephemeral=True)
            return

        ticket_key = f"{inter.user.id}:{ticket_cat.key}"
        existing_record = store.data.get("tickets", {}).get(ticket_key)
        existing_id = ticket_channel_id(existing_record) if existing_record else None
        existing = inter.guild.get_channel(int(existing_id)) if existing_id else None
        if existing:
            await inter.response.send_message(embed=embed("Ticket already exists", f"You already have a ticket: {existing.mention}", 0xFEE75C), ephemeral=True)
            return

        cat = inter.guild.get_channel(ticket_cat.channel_id)
        support = inter.guild.get_role(cfg.support_role_id)
        overwrites = {
            inter.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            inter.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            inter.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support:
            overwrites[support] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ch = await inter.guild.create_text_channel(
            name=f"{ticket_cat.key}-{slug(inter.user.name)}",
            category=cat if isinstance(cat, discord.CategoryChannel) else None,
            overwrites=overwrites,
            topic=f"Ticket owner: {inter.user.id} | category: {ticket_cat.key}",
            reason=f"Ticket created by {inter.user}",
        )
        store.data.setdefault("tickets", {})[ticket_key] = {
            "channel_id": str(ch.id),
            "owner_id": str(inter.user.id),
            "category": ticket_cat.key,
            "claimed_by": None,
            "created_at": utc_now(),
        }
        await store.save()

        await ch.send(
            content=inter.user.mention,
            embed=embed(ticket_cat.label, "Opisz problem. Support odpowie jak najszybciej.", 0x57F287),
            view=CloseView(),
        )
        await inter.response.send_message(embed=embed("Ticket utworzony", ch.mention, 0x57F287), ephemeral=True)
        await log(inter.guild, "Ticket utworzony", f"{inter.user.mention} -> {ch.mention}\nKategoria: `{ticket_cat.label}`")



class CloseView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Zamknij", style=discord.ButtonStyle.red, custom_id="ticket:close")
    async def close_button(self, inter: discord.Interaction, _: discord.ui.Button) -> None:
        await close_ticket(inter, "Closed via button")


intents = discord.Intents.default()
intents.message_content = False
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


@bot.event
async def on_ready() -> None:
    await store.load()
    bot.add_view(TicketView())
    bot.add_view(CloseView())
    await bot.change_presence(activity=discord.CustomActivity(name="Watching for any tickets..."))
    guild = discord.Object(id=cfg.guild_id) if cfg.guild_id else None
    if guild:
        tree.copy_global_to(guild=guild)
        try:
            await tree.sync(guild=guild)
        except discord.Forbidden:
            print(f"Cannot sync guild commands: bot has no access to GUILD_ID={cfg.guild_id}. Falling back to global sync.")
            await tree.sync()
    else:
        await tree.sync()
    print(f"Logged in as {bot.user} ({bot.user.id})")


@tree.command(name="ticket_panel", description="Send the ticket creation panel.")
async def ticket_panel(inter: discord.Interaction) -> None:
    if not await require_staff(inter):
        return
    await reply(inter, embed=embed("Support", "Choose a ticket category.", 0x5865F2))
    if isinstance(inter.channel, discord.TextChannel):
        await inter.channel.send(embed=embed("Support", "Choose a ticket category.", 0x5865F2), view=TicketView())


@tree.command(name="claim", description="Przypisz aktualny ticket do siebie.")
async def claim(inter: discord.Interaction) -> None:
    if not inter.guild or not isinstance(inter.channel, discord.TextChannel):
        return
    if not isinstance(inter.user, discord.Member):
        await reply(inter, embed=embed("Missing permissions", "This command is staff-only.", 0xED4245), ephemeral=True)
        return
    await inter.response.defer()
    ticket_key, ticket = ticket_by_channel(inter.channel)
    if not ticket_key or ticket is None:
        await reply(inter, embed=embed("Not a ticket", "Use this command in a ticket channel.", 0xED4245), ephemeral=True)
        return
    if not await require_ticket_manager(inter, ticket):
        return
    claimed_by = ticket.get("claimed_by")
    if claimed_by and claimed_by != str(inter.user.id):
        await reply(inter, embed=embed("Ticket claimed", f"This ticket is already assigned to <@{claimed_by}>.", 0xED4245), ephemeral=True)
        return
    support = inter.guild.get_role(cfg.support_role_id)
    if support and inter.channel.overwrites_for(support).send_messages is not False:
        await inter.channel.set_permissions(support, view_channel=True, send_messages=False, read_message_history=True)
    for target, overwrite in inter.channel.overwrites.items():
        if isinstance(target, discord.Role) and target.id == cfg.support_role_id and overwrite.view_channel is not False and overwrite.send_messages is not False:
            await inter.channel.set_permissions(target, view_channel=True, send_messages=False, read_message_history=True)
        if isinstance(target, discord.Member) and target != inter.user and is_support_only(target) and overwrite.send_messages is not False:
            await inter.channel.set_permissions(target, view_channel=True, send_messages=False, read_message_history=True)
    await inter.channel.set_permissions(inter.user, view_channel=True, send_messages=True, read_message_history=True)
    ticket["claimed_by"] = str(inter.user.id)
    ticket["claimed_at"] = utc_now()
    await store.save()
    await reply(inter, embed=embed("Ticket claimed", f"{inter.user.mention} claimed this ticket.", 0x57F287))


@tree.command(name="add", description="Add a user to the current ticket.")
@app_commands.describe(user="User")
async def add(inter: discord.Interaction, user: discord.Member) -> None:
    if not inter.guild or not isinstance(inter.channel, discord.TextChannel):
        return
    ticket_key, ticket = ticket_by_channel(inter.channel)
    if not ticket_key or ticket is None:
        await reply(inter, embed=embed("Not a ticket", "Use this command in a ticket channel.", 0xED4245), ephemeral=True)
        return
    if not await require_ticket_manager(inter, ticket):
        return
    await inter.channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
    await reply(inter, embed=embed("Added to ticket", f"{user.mention} has access to this ticket.", 0x57F287))


@tree.command(name="points", description="Check points.")
async def points(inter: discord.Interaction, user: discord.Member | None = None) -> None:
    target = user or inter.user
    data = store.user(target.id)
    await reply(inter, embed=embed("Points", f"{target.mention}\nPoints: **{data['points']}**\nClaims: **{data['claims']}**", 0x5865F2), ephemeral=user is None)


@tree.command(name="give_points", description="Add points to a user. Admin only.")
@app_commands.describe(user="User", points="Point amount", reason="Reason")
async def give_points(inter: discord.Interaction, user: discord.Member, points: int, reason: str = "None") -> None:
    if not inter.guild or not await require_admin(inter):
        return
    if not 1 <= points <= 100000:
        await reply(inter, embed=embed("Invalid number", "Point range: 1..100000.", 0xED4245), ephemeral=True)
        return
    total = await store.add_points(user.id, points)
    await reply(inter, embed=embed("Points dodane", f"{user.mention}: +{points}\nTotal: **{total}**\nReason: {reason}", 0x57F287))


@tree.command(name="remove_points", description="Remove points from a user. Admin only.")
@app_commands.describe(user="User", points="Point amount", reason="Reason")
async def remove_points(inter: discord.Interaction, user: discord.Member, points: int, reason: str = "None") -> None:
    if not inter.guild or not await require_admin(inter):
        return
    if not 1 <= points <= 100000:
        await reply(inter, embed=embed("Invalid number", "Point range: 1..100000.", 0xED4245), ephemeral=True)
        return
    total = await store.add_points(user.id, -points)
    await reply(inter, embed=embed("Points removed", f"{user.mention}: -{points}\nTotal: **{total}**\nReason: {reason}", 0xED4245))


@tree.command(name="quota", description="Check point quota.")
async def quota(inter: discord.Interaction, user: discord.Member | None = None) -> None:
    target = user or inter.user
    pts = int(store.user(target.id).get("points", 0))
    goal = biweekly_goal()
    pct = min(100, round((pts / goal) * 100))
    await reply(inter, embed=embed("Quota", f"{target.mention}\n{pts}/{goal} pkt ({pct}%)", 0xFEE75C), ephemeral=user is None)


@tree.command(name="stats", description="Show ticket stats.")
async def stats(inter: discord.Interaction, user: discord.Member | None = None) -> None:
    target = user or inter.user
    await reply(inter, embed=ticket_stats_embed(target, store.user(target.id)), ephemeral=user is None)


@tree.command(name="leaderboard", description="Staff ticket leaderboard.")
@app_commands.choices(sort=[app_commands.Choice(name="biweekly", value="biweekly"), app_commands.Choice(name="lifetime", value="lifetime")])
async def leaderboard(inter: discord.Interaction, sort: app_commands.Choice[str] | None = None) -> None:
    if not inter.guild:
        return
    mode = sort.value if sort else "biweekly"
    key = "lifetime_tickets" if mode == "lifetime" else "biweekly_tickets"
    rows = sorted(store.data.get("users", {}).items(), key=lambda item: int(item[1].get(key, 0)), reverse=True)[:10]
    lines = []
    for idx, (uid, data) in enumerate(rows):
        count = int(data.get(key, 0))
        if count > 0:
            lines.append(f"{idx + 1}. **{await member_name(inter.guild, uid)}** - {count} tickets")
    await reply(inter, embed=embed(f"Leaderboard - {mode}", "\n".join(lines) or "No ticket data yet.", 0xFEE75C))


@tree.command(name="biweekly-check", description="Check who hit the biweekly goal.")
async def biweekly_check(inter: discord.Interaction) -> None:
    if not inter.guild:
        return
    goal = biweekly_goal()
    seen = [(uid, store.user(int(uid))) for uid in store.data.get("users", {}) if int(store.user(int(uid)).get("biweekly_tickets", 0)) > 0]
    hit = [(uid, data) for uid, data in seen if int(data.get("biweekly_tickets", 0)) >= goal]
    miss = [(uid, data) for uid, data in seen if int(data.get("biweekly_tickets", 0)) < goal]
    hit_lines = [f"OK **{await member_name(inter.guild, uid)}** - {int(data['biweekly_tickets'])}/{goal}" for uid, data in hit]
    miss_lines = [f"NO **{await member_name(inter.guild, uid)}** - {int(data['biweekly_tickets'])}/{goal}" for uid, data in miss]
    desc = f"Goal: {goal} tickets | Period started: {period_age()}\n\nHit Goal ({len(hit)})\n{chr(10).join(hit_lines) or 'Nobody yet.'}\n\nHavent Hit Goal ({len(miss)})\n{chr(10).join(miss_lines) or 'Nobody yet.'}"
    await reply(inter, embed=embed("Biweekly Check", desc, 0x5865F2))


@tree.command(name="setup-biweekly", description="Reset the biweekly period. Admin only.")
@app_commands.describe(goal="New biweekly ticket goal")
async def setup_biweekly(inter: discord.Interaction, goal: int) -> None:
    if not inter.guild or not await require_admin(inter):
        return
    if not 1 <= goal <= 100000:
        await reply(inter, embed=embed("Invalid number", "Goal must be in range 1..100000.", 0xED4245), ephemeral=True)
        return
    await store.reset_biweekly(goal)
    await reply(inter, embed=embed("New Biweekly Period Started", f"Goal: {biweekly_goal()}\nStarted: {discord.utils.format_dt(period_started(), 'F')}", 0x3498DB))


@tree.command(name="rewards", description="Show point rewards.")
async def rewards(inter: discord.Interaction) -> None:
    rows = [f"{r['id']} - **{r['name']}** ({r['cost']} pkt)" for r in load_rewards()]
    await reply(inter, embed=embed("Rewards", "\n".join(rows) or "None nagrod.", 0x5865F2), ephemeral=True)


@tree.command(name="claim_reward", description="Claim a point reward.")
@app_commands.describe(reward_id="ID z /rewards")
async def claim_reward(inter: discord.Interaction, reward_id: str) -> None:
    if not inter.guild:
        return
    reward = next((r for r in load_rewards() if r["id"].lower() == reward_id.lower()), None)
    if not reward:
        await reply(inter, embed=embed("Not found", "That reward does not exist.", 0xED4245), ephemeral=True)
        return
    user = store.user(inter.user.id)
    if int(user["points"]) < int(reward["cost"]):
        await reply(inter, embed=embed("Not enough points", f"Required: {reward['cost']} pkt.", 0xED4245), ephemeral=True)
        return
    total = await store.add_points(inter.user.id, -int(reward["cost"]))
    await reply(inter, embed=embed("Reward claimed", f"Reward: **{reward['name']}**\nRemaining: **{total}** pkt", 0x57F287), ephemeral=True)


async def close_ticket(inter: discord.Interaction, reason: str) -> None:
    if not inter.guild or not isinstance(inter.channel, discord.TextChannel):
        return
    ticket_key, ticket = ticket_by_channel(inter.channel)
    if not ticket_key or ticket is None:
        await reply(inter, embed=embed("Not a ticket", "Use this command in a ticket channel.", 0xED4245), ephemeral=True)
        return
    if not await require_ticket_manager(inter, ticket):
        return
    award_uid = int(ticket.get("claimed_by") or inter.user.id)
    store.data["tickets"].pop(ticket_key, None)
    awarded = await store.add_closed_ticket(award_uid)
    bonus = f"\nAwarded to <@{award_uid}>: +1 point, {awarded['biweekly_tickets']} / {biweekly_goal()} quota"
    await reply(inter, embed=embed("Closing", f"Channel will be deleted in 10 seconds.{bonus}", 0xED4245))
    await log(inter.guild, "Ticket closed", f"Closed by: {inter.user.mention}\nReason: {reason}", 0xED4245)
    await asyncio.sleep(10)
    await inter.channel.delete(reason=reason)


@tree.command(name="close", description="Close the current ticket.")
async def close(inter: discord.Interaction, reason: str = "Closed by command") -> None:
    await close_ticket(inter, reason)


bot.run(cfg.token)
