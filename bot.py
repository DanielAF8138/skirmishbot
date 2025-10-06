import discord
import json
import math
import random
import os
from functools import partial
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from discord import app_commands
from discord.ui import Button, View
from discord import Embed
from graphviz import Digraph


#################################################################################
#helpers
#################################################################################
DATA_FILE = "server_leaderboard.json"
ACTIVE_CHALLENGES_FILE = "active_challenges.json"

# -----------------------------
# Helper functions for ELO and storage
# -----------------------------
def load_data(file):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_data(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def get_rating(guild_id, user_id, data):
    guild_id = str(guild_id)
    user_id = str(user_id)
    if guild_id not in data:
        data[guild_id] = {}
    if user_id not in data[guild_id]:
        data[guild_id][user_id] = {"elo": 1000, "wins": 0, "losses": 0}
    return data[guild_id][user_id]

def update_elo(guild_id, winner_id, loser_id, data, k=32):
    winner = get_rating(guild_id, winner_id, data)
    loser = get_rating(guild_id, loser_id, data)

    expected_winner = 1 / (1 + math.pow(10, (loser["elo"] - winner["elo"]) / 400))
    expected_loser = 1 - expected_winner

    winner["elo"] += round(k * (1 - expected_winner))
    loser["elo"] += round(k * (0 - expected_loser))

    winner["wins"] += 1
    loser["losses"] += 1

    data[str(guild_id)][str(winner_id)] = winner
    data[str(guild_id)][str(loser_id)] = loser


class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.leaderboard_data = load_data(DATA_FILE)
        self.active_challenges = load_data(ACTIVE_CHALLENGES_FILE)

    async def on_ready(self):
        print(f"✅ Logged in as {client.user}")
        try:
            guild = discord.Object(id=868216102944133181)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} commands to guild {guild.id}")

        except Exception as e:    
            print(f"Error syncing: {e}")


client = MyClient()


# -----------------------------
# /challenge command (full, with map selection)
# -----------------------------
@client.tree.command(name="challenge", description="Challenge another user to a duel!")
@app_commands.describe(opponent="The user you want to challenge")
async def challenge(interaction: discord.Interaction, opponent: discord.User):
    challenger = interaction.user
    guild_id = str(interaction.guild.id)

    if opponent == challenger:
        embed = discord.Embed(
            title="❌ Error",
            description="You can't challenge yourself!",
            color=0xFF0000
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if guild_id not in client.active_challenges:
        client.active_challenges[guild_id] = []

    # Check if either user is already in a challenge
    for ch in client.active_challenges[guild_id]:
        if challenger.id in (ch["challenger"], ch["opponent"]) or opponent.id in (ch["challenger"], ch["opponent"]):
            embed = discord.Embed(
                title="❌ Error",
                description="One of the users is already in an active challenge!",
                color=0xFF0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

    # Add to active challenges
    client.active_challenges[guild_id].append({
        "challenger": challenger.id,
        "opponent": opponent.id
    })
    save_data(ACTIVE_CHALLENGES_FILE, client.active_challenges)

    # Initial challenge embed
    embed = discord.Embed(
        title="⚔️ New Challenge!",
        description=f"{challenger.mention} has challenged {opponent.mention}!\nDo you accept?",
        color=0x00FFFF
    )

    # Accept/Decline buttons
    accept_button = discord.ui.Button(label="✅ Accept", style=discord.ButtonStyle.success)
    decline_button = discord.ui.Button(label="❌ Decline", style=discord.ButtonStyle.danger)
    view = discord.ui.View()
    view.add_item(accept_button)
    view.add_item(decline_button)

    await interaction.response.send_message(embed=embed, view=view)

    # -----------------------------
    # Accept callback
    # -----------------------------
    async def accept_callback(button_interaction: discord.Interaction):
        if button_interaction.user != opponent:
            await button_interaction.response.send_message(
                embed=discord.Embed(title="❌ Error", description="This isn’t your challenge!", color=0xFF0000),
                ephemeral=True
            )
            return

        # Pick a random map
        map_choice = random.choice(["Map A", "Map B", "Map C"])

        # Notify challenge accepted and map
        await button_interaction.response.edit_message(
            embed=discord.Embed(
                title="⚔️ Challenge Accepted!",
                description=f"{opponent.mention} accepted the challenge!\n"
                            f"The match will take place on **{map_choice}**.\n\n"
                            f"Select the winner (25 minutes to choose):",
                color=0x00FF00
            ),
            view=None
        )

        # Winner selection buttons
        winner_view = discord.ui.View(timeout=1500)  # 25 min
        challenger_button = discord.ui.Button(label=challenger.display_name, style=discord.ButtonStyle.primary, custom_id="challenger")
        opponent_button = discord.ui.Button(label=opponent.display_name, style=discord.ButtonStyle.success, custom_id="opponent")

        async def select_winner_callback(winner_interaction: discord.Interaction):
            if winner_interaction.user.id not in (challenger.id, opponent.id):
                await winner_interaction.response.send_message(
                    embed=discord.Embed(title="❌ Error", description="Only participants can select the winner!", color=0xFF0000),
                    ephemeral=True
                )
                return

            # Determine winner based on button clicked
            if winner_interaction.data['custom_id'] == "challenger":
                winner = challenger
                loser = opponent
            else:
                winner = opponent
                loser = challenger

            # Update ELO
            update_elo(guild_id, winner.id, loser.id, client.leaderboard_data)
            save_data(DATA_FILE, client.leaderboard_data)

            # Remove from active challenges
            client.active_challenges[guild_id] = [
                c for c in client.active_challenges[guild_id]
                if not (c["challenger"] == challenger.id and c["opponent"] == opponent.id)
            ]
            save_data(ACTIVE_CHALLENGES_FILE, client.active_challenges)

            await winner_interaction.response.edit_message(
                embed=discord.Embed(
                    title="🏆 Match Result",
                    description=f"{winner.mention} won the match against {loser.mention}!\n📈 ELO updated.",
                    color=0xFFD700
                ),
                view=None
            )
            winner_view.stop()

        challenger_button.callback = select_winner_callback
        opponent_button.callback = select_winner_callback
        winner_view.add_item(challenger_button)
        winner_view.add_item(opponent_button)

        winner_msg = await button_interaction.followup.send(
            embed=discord.Embed(title="⚔️ Who won?", description="Select the winner:", color=0x00FFFF),
            view=winner_view
        )

        # Handle timeout
        async def on_timeout():
            client.active_challenges[guild_id] = [
                c for c in client.active_challenges[guild_id]
                if not (c["challenger"] == challenger.id and c["opponent"] == opponent.id)
            ]
            save_data(ACTIVE_CHALLENGES_FILE, client.active_challenges)
            try:
                await winner_msg.edit(embed=discord.Embed(
                    title="⌛ Challenge Timed Out",
                    description="The match was cancelled due to timeout.",
                    color=0xFF0000
                ), view=None)
            except:
                pass

        winner_view.on_timeout = on_timeout

    # -----------------------------
    # Decline callback
    # -----------------------------
    async def decline_callback(button_interaction: discord.Interaction):
        if button_interaction.user != opponent:
            await button_interaction.response.send_message(
                embed=discord.Embed(title="❌ Error", description="This isn’t your challenge!", color=0xFF0000),
                ephemeral=True
            )
            return

        client.active_challenges[guild_id] = [
            c for c in client.active_challenges[guild_id]
            if not (c["challenger"] == challenger.id and c["opponent"] == opponent.id)
        ]
        save_data(ACTIVE_CHALLENGES_FILE, client.active_challenges)

        await button_interaction.response.edit_message(
            embed=discord.Embed(
                title="🚫 Challenge Declined",
                description=f"{opponent.mention} declined the challenge from {challenger.mention}.",
                color=0xFF0000
            ),
            view=None
        )

    accept_button.callback = accept_callback
    decline_button.callback = decline_callback



# # -----------------------------
# # /leaderboard command (3-column fields) with fetch_member
# # -----------------------------
# @client.tree.command(name="leaderboard", description="View the top players by ELO in this server", guild=GUILD_ID)
# async def leaderboard(interaction: discord.Interaction):
#     guild_id = str(interaction.guild.id)
#     data = client.leaderboard_data

#     if guild_id not in data or not data[guild_id]:
#         embed = discord.Embed(
#             title="📉 No matches yet!",
#             description="No matches have been played in this server yet!",
#             color=0xFF0000
#         )
#         await interaction.response.send_message(embed=embed)
#         return

#     sorted_players = sorted(data[guild_id].items(), key=lambda x: x[1]["elo"], reverse=True)[:10]

#     embed = discord.Embed(
#         title="🏆 Server Leaderboard 🏆",
#         color=0xFFD700
#     )

#     usernames = ""
#     elos = ""
#     wls = ""

#     for i, (user_id, stats) in enumerate(sorted_players, start=1):
#         try:
#             member = await interaction.guild.fetch_member(int(user_id))
#             username = member.display_name
#         except:
#             username = f"User {user_id}"  # fallback if not found
#         usernames += f"{i}. {username}\n"
#         elos += f"{stats['elo']}\n"
#         wls += f"{stats['wins']}/{stats['losses']}\n"

#     embed.add_field(name="Username", value=usernames or "-", inline=True)
#     embed.add_field(name="ELO", value=elos or "-", inline=True)
#     embed.add_field(name="W/L", value=wls or "-", inline=True)

#     embed.set_footer(text=f"Total players: {len(sorted_players)}")

#     await interaction.response.send_message(embed=embed)


# -----------------------------
# /leaderboard command 
# -----------------------------

@client.tree.command(name="leaderboard", description="View the top players by ELO in this server", )
async def leaderboard(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    data = client.leaderboard_data

    if guild_id not in data or not data[guild_id]:
        embed = discord.Embed(
            title="📉 No matches yet!",
            description="No matches have been played in this server yet!",
            color=0xFF0000
        )
        await interaction.response.send_message(embed=embed)
        return

    sorted_players = sorted(data[guild_id].items(), key=lambda x: x[1]["elo"], reverse=True)[:10]

    # Image setup
    width, height = 600, 60 + 70 * len(sorted_players)
    image = Image.new("RGBA", (width, height), (30, 30, 30, 255))
    draw = ImageDraw.Draw(image)
    
    # Font
    font = ImageFont.truetype("arial.ttf", 24)
    
    # Right-aligned column for stats
    stats_x = 550

    y_offset = 20
    for i, (user_id, stats) in enumerate(sorted_players, start=1):
        # Fetch member
        try:
            member = await interaction.guild.fetch_member(int(user_id))
            username = member.display_name

            # Fetch avatar bytes directly from Discord
            avatar_bytes = await member.display_avatar.read()
            avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((50, 50))
        except:
            username = f"User {user_id}"
            avatar = Image.new("RGBA", (50, 50), (100, 100, 100, 255))  # gray placeholder

        # Draw ranking number to the left of avatar
        rank_text = f"{i}."
        rank_width = draw.textlength(rank_text, font=font)
        draw.text((20, int(y_offset + 15)), rank_text, font=font, fill="white")  # vertically centered

        # Paste avatar next to rank number (coordinates must be int)
        image.paste(avatar, (int(40 + rank_width), int(y_offset)), avatar)

        # Draw username next to avatar
        draw.text((int(100 + rank_width), int(y_offset)), username, font=font, fill="white")

        # Draw ELO + win/loss (right-aligned)
        stats_text = f"{stats['elo']} ({stats['wins']}/{stats['losses']})"
        stats_width = draw.textlength(stats_text, font=font)
        draw.text((int(stats_x - stats_width), int(y_offset)), stats_text, font=font, fill="white")

        y_offset += 70

    # Convert image to BytesIO
    with BytesIO() as image_binary:
        image.save(image_binary, "PNG")
        image_binary.seek(0)

        # Create embed with image
        file = discord.File(fp=image_binary, filename="leaderboard.png")
        embed = discord.Embed(color=0xFFD700)
        embed.set_image(url="attachment://leaderboard.png")
        embed.set_footer(text=f"Total players: {len(sorted_players)}")

        await interaction.response.send_message(embed=embed, file=file)




# -----------------------------
# /reset_leaderboard command
# -----------------------------
@client.tree.command(name="reset_leaderboard", description="Reset this server's leaderboard (admin only)")
async def reset_leaderboard(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    if not interaction.user.guild_permissions.administrator:
        embed = Embed(title="❌ Permission Denied", description="Only administrators can reset the leaderboard.", color=0xFF0000)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    client.leaderboard_data[guild_id] = {}
    save_data(DATA_FILE, client.leaderboard_data)

    embed = Embed(title="✅ Leaderboard Reset", description="The leaderboard has been reset for this server!", color=0x00FF00)
    await interaction.response.send_message(embed=embed)



# # -----------------------------
# # Start Tournament
# # -----------------------------
# async def start_tournament(channel, players, creator):
#     random.shuffle(players)
#     state = {"round": 1, "players": players, "winners": []}
#     await run_tournament_round(channel, state, creator)

# # -----------------------------
# # Run Tournament Round
# # -----------------------------
# async def run_tournament_round(channel, state, creator):
#     players = state["players"]
#     round_num = state["round"]

#     await channel.send(embed=discord.Embed(
#         title=f"🏆 Round {round_num} Begins!",
#         description=f"{len(players)} players remain.",
#         color=0xFFD700
#     ))

#     matches = []
#     state["winners"] = []
#     i = 0
#     while i < len(players):
#         if i + 1 < len(players):
#             matches.append((players[i], players[i + 1]))
#         else:
#             state["winners"].append(players[i])
#             await channel.send(f"🎉 {players[i].mention} advances with a bye!")
#         i += 2

#     state["matches_remaining"] = len(matches)

#     for player1, player2 in matches:
#         view = View(timeout=None)
#         button_p1 = Button(label=player1.display_name, style=discord.ButtonStyle.primary)
#         button_p2 = Button(label=player2.display_name, style=discord.ButtonStyle.success)

#         async def winner_callback(interaction: discord.Interaction, winner, loser):
#             if interaction.user.id not in (winner.id, loser.id, creator.id):
#                 await interaction.response.send_message("❌ Not authorized!", ephemeral=True)
#                 return
#             state["winners"].append(winner)
#             await interaction.response.edit_message(
#                 embed=discord.Embed(title="🏆 Match Result",
#                                     description=f"{winner.mention} defeated {loser.mention}!",
#                                     color=0xFFD700),
#                 view=None
#             )
#             state["matches_remaining"] -= 1
#             if state["matches_remaining"] == 0:
#                 if len(state["winners"]) == 1:
#                     await channel.send(embed=discord.Embed(
#                         title="👑 Champion Crowned!",
#                         description=f"🏆 {state['winners'][0].mention} is the champion!",
#                         color=0xFFD700
#                     ))
#                 else:
#                     state["players"] = state["winners"]
#                     state["round"] += 1
#                     await run_tournament_round(channel, state, creator)

#         # Use partial to capture match players
#         from functools import partial
#         button_p1.callback = partial(winner_callback, winner=player1, loser=player2)
#         button_p2.callback = partial(winner_callback, winner=player2, loser=player1)
#         view.add_item(button_p1)
#         view.add_item(button_p2)

#         embed = discord.Embed(
#             title=f"⚔️ Matchup (Round {round_num})",
#             description=f"{player1.mention} vs {player2.mention}\nParticipants or {creator.display_name} can declare the winner.",
#             color=0x00BFFF
#         )
#         await channel.send(embed=embed, view=view)



# -----------------------------
# /tournament command
# -----------------------------

# -----------------------------
# /tournament command
# -----------------------------
@client.tree.command(
    name="tournament",
    description="Start a tournament (4, 8, or 16 players)",
    guild=GUILD_ID
)
@app_commands.describe(
    size="Number of players: 4, 8, or 16"
)
async def tournament(interaction: discord.Interaction, size: int):
    if size not in [4, 8, 16]:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="❌ Invalid Size",
                description="You must choose 4, 8, or 16 players.",
                color=0xFF0000
            ),
            ephemeral=True
        )
        return

    creator = interaction.user

    # -----------------------------
    # NORMAL SIGNUP MODE
    # -----------------------------
    players = []
    join_view = View(timeout=None)

    join_button = Button(label="Join Tournament", style=discord.ButtonStyle.primary)
    cancel_button = Button(label="Cancel Tournament", style=discord.ButtonStyle.danger)
    join_view.add_item(join_button)
    join_view.add_item(cancel_button)

    def get_signup_embed():
        player_list = "\n".join([f"{i+1}. {p.display_name}" for i, p in enumerate(players)]) or "No players joined yet."
        return discord.Embed(
            title="🎮 Tournament Signup",
            description=f"Tournament started by {creator.mention}\n"
                        f"Size: **{size} players**\n\n"
                        f"✅ {len(players)}/{size} players joined\n{player_list}",
            color=0x00FF00
        )

    await interaction.response.send_message(embed=get_signup_embed(), view=join_view)

    async def join_callback(button_interaction: discord.Interaction):
        nonlocal players
        if button_interaction.user.id in [p.id for p in players]:
            await button_interaction.response.send_message("❌ You already joined!", ephemeral=True)
            return
        if len(players) >= size:
            await button_interaction.response.send_message("❌ Tournament is full!", ephemeral=True)
            return
        players.append(button_interaction.user)
        await button_interaction.response.edit_message(embed=get_signup_embed(), view=join_view)

        if len(players) == size:
            join_view.stop()
            await start_tournament(button_interaction.channel, players, creator)

    async def cancel_callback(button_interaction: discord.Interaction):
        if button_interaction.user.id != creator.id:
            await button_interaction.response.send_message("❌ Only the tournament creator can cancel!", ephemeral=True)
            return
        join_view.stop()
        await button_interaction.response.edit_message(
            embed=discord.Embed(
                title="🚫 Tournament Cancelled",
                description=f"The tournament started by {creator.mention} was cancelled.",
                color=0xFF0000
            ),
            view=None
        )

    join_button.callback = join_callback
    cancel_button.callback = cancel_callback


# @client.tree.command(
#     name="tournament",
#     description="Start a tournament (4, 8, or 16 players)",
#     guild=GUILD_ID
# )
# @app_commands.describe(
#     size="Number of players: 4, 8, or 16",
#     test="Enable test mode with fake players"
# )
# async def tournament(interaction: discord.Interaction, size: int, test: bool = False):
#     if size not in [4, 8, 16]:
#         await interaction.response.send_message(
#             embed=discord.Embed(
#                 title="❌ Invalid Size",
#                 description="You must choose 4, 8, or 16 players.",
#                 color=0xFF0000
#             ),
#             ephemeral=True
#         )
#         return

#     creator = interaction.user

#     # -----------------------------
#     # TEST MODE
#     # -----------------------------
#     if test:
#         class FakeUser:
#             def __init__(self, name):
#                 self.display_name = name
#                 self.mention = f"@{name}"
#                 self.id = hash(name) & 0xFFFFFFF
#                 self.avatar_url = None

#         players = [FakeUser(f"Player{i+1}") for i in range(size)]
#         await interaction.response.send_message(embed=discord.Embed(
#             title="🧪 Test Tournament",
#             description=f"Running test tournament with **{size} fake players**.",
#             color=0x00FF00
#         ))
#         await start_tournament(interaction.channel, players, creator)
#         return

#     # -----------------------------
#     # NORMAL SIGNUP MODE
#     # -----------------------------
#     players = []
#     join_view = View(timeout=None)

#     join_button = Button(label="Join Tournament", style=discord.ButtonStyle.primary)
#     cancel_button = Button(label="Cancel Tournament", style=discord.ButtonStyle.danger)
#     join_view.add_item(join_button)
#     join_view.add_item(cancel_button)

#     def get_signup_embed():
#         player_list = "\n".join([f"{i+1}. {p.display_name}" for i, p in enumerate(players)]) or "No players joined yet."
#         return discord.Embed(
#             title="🎮 Tournament Signup",
#             description=f"Tournament started by {creator.mention}\n"
#                         f"Size: **{size} players**\n\n"
#                         f"✅ {len(players)}/{size} players joined\n{player_list}",
#             color=0x00FF00
#         )

#     await interaction.response.send_message(embed=get_signup_embed(), view=join_view)

#     async def join_callback(button_interaction: discord.Interaction):
#         nonlocal players
#         if button_interaction.user.id in [p.id for p in players]:
#             await button_interaction.response.send_message("❌ You already joined!", ephemeral=True)
#             return
#         if len(players) >= size:
#             await button_interaction.response.send_message("❌ Tournament is full!", ephemeral=True)
#             return
#         players.append(button_interaction.user)
#         await button_interaction.response.edit_message(embed=get_signup_embed(), view=join_view)

#         if len(players) == size:
#             join_view.stop()
#             await start_tournament(button_interaction.channel, players, creator)

#     async def cancel_callback(button_interaction: discord.Interaction):
#         if button_interaction.user.id != creator.id:
#             await button_interaction.response.send_message("❌ Only the tournament creator can cancel!", ephemeral=True)
#             return
#         join_view.stop()
#         await button_interaction.response.edit_message(
#             embed=discord.Embed(
#                 title="🚫 Tournament Cancelled",
#                 description=f"The tournament started by {creator.mention} was cancelled.",
#                 color=0xFF0000
#             ),
#             view=None
#         )

#     join_button.callback = join_callback
    cancel_button.callback = cancel_callback


# -----------------------------
# Start Tournament
# -----------------------------
async def start_tournament(channel, players, creator):
    random.shuffle(players)
    state = {
        "round": 1,
        "players": players,
        "winners": [],
        "winners_map": {},  # match_id -> winner
        "player_names": [p.display_name for p in players]
    }

    # Send initial full bracket
    bracket_img = generate_full_bracket(state["player_names"], state["winners_map"])
    await channel.send(file=discord.File(fp=bracket_img, filename="bracket.png"))

    await run_tournament_round(channel, state, creator)


# -----------------------------
# Generate Full Bracket
# -----------------------------
def generate_full_bracket(players, winners_map=None):
    n = len(players)
    rounds = 0
    temp = n
    while temp > 1:
        temp //= 2
        rounds += 1

    dot = Digraph(comment="Tournament Bracket", format='png')
    dot.attr(rankdir='TB', bgcolor='white')
    dot.attr('node', shape='box', style='filled', color='black', fillcolor='white', fontcolor='black')

    # First round nodes
    match_ids = {}
    for i, player in enumerate(players):
        node_id = f"R0_M{i}"
        label = player
        if winners_map and node_id in winners_map:
            label = winners_map[node_id]
            dot.node(node_id, label=label, fillcolor='black', fontcolor='white')
        else:
            dot.node(node_id, label=label)
        match_ids[i] = node_id

    # Subsequent rounds
    prev_round = list(match_ids.values())
    for r in range(1, rounds+1):
        curr_round = []
        for i in range(0, len(prev_round), 2):
            node_id = f"R{r}_M{i//2}"
            label = winners_map.get(node_id, "") if winners_map else ""
            fillcolor = 'black' if node_id in (winners_map or {}) else 'white'
            fontcolor = 'white' if fillcolor == 'black' else 'black'
            dot.node(node_id, label=label, fillcolor=fillcolor, fontcolor=fontcolor)
            dot.edge(prev_round[i], node_id)
            if i+1 < len(prev_round):
                dot.edge(prev_round[i+1], node_id)
            curr_round.append(node_id)
        prev_round = curr_round

    img_bytes = BytesIO(dot.pipe())
    img_bytes.seek(0)
    return img_bytes


# -----------------------------
# Run Tournament Round (fixed)
# -----------------------------
async def run_tournament_round(channel, state, creator):
    players = state["players"]
    round_num = state["round"]

    await channel.send(embed=discord.Embed(
        title=f"🏆 Round {round_num} Begins!",
        description=f"{len(players)} players remain.",
        color=0xFFD700
    ))

    matches = []
    state["winners"] = []
    i = 0
    while i < len(players):
        if i + 1 < len(players):
            matches.append((players[i], players[i + 1]))
        else:
            # Bye for odd number of players
            state["winners"].append(players[i])
            await channel.send(f"🎉 {players[i].mention} advances with a bye!")
        i += 2

    state["matches_remaining"] = len(matches)

    for m_idx, (player1, player2) in enumerate(matches):
        view = View(timeout=None)
        button_p1 = Button(label=player1.display_name, style=discord.ButtonStyle.primary)
        button_p2 = Button(label=player2.display_name, style=discord.ButtonStyle.success)

        # Compute the correct node ID for the winner in the bracket
        next_round_node_id = f"R{round_num}_M{m_idx}"

        async def winner_callback(interaction: discord.Interaction, winner, loser, match_node_id=next_round_node_id):
            if interaction.user.id not in (winner.id, loser.id, creator.id):
                await interaction.response.send_message("❌ Not authorized!", ephemeral=True)
                return

            state["winners"].append(winner)
            state["winners_map"][match_node_id] = winner.display_name

            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="🏆 Match Result",
                    description=f"{winner.mention} defeated {loser.mention}!",
                    color=0xFFD700
                ),
                view=None
            )

            state["matches_remaining"] -= 1

            if state["matches_remaining"] == 0:
                # Send updated bracket
                bracket_img = generate_full_bracket(state["player_names"], state["winners_map"])
                await channel.send(file=discord.File(fp=bracket_img, filename="bracket.png"))

                if len(state["winners"]) == 1:
                    await channel.send(embed=discord.Embed(
                        title="👑 Champion Crowned!",
                        description=f"🏆 {state['winners'][0].mention} is the champion!",
                        color=0xFFD700
                    ))
                else:
                    state["players"] = state["winners"]
                    state["round"] += 1
                    await run_tournament_round(channel, state, creator)

        # Assign callbacks with correct node ID
        button_p1.callback = partial(winner_callback, winner=player1, loser=player2)
        button_p2.callback = partial(winner_callback, winner=player2, loser=player1)
        view.add_item(button_p1)
        view.add_item(button_p2)

        embed = discord.Embed(
            title=f"⚔️ Matchup (Round {round_num})",
            description=f"{player1.mention} vs {player2.mention}\nParticipants or {creator.display_name} can declare the winner.",
            color=0x00BFFF
        )
        await channel.send(embed=embed, view=view)



######################


# -----------------------------
# /help command
# -----------------------------
@client.tree.command(name="help", description="Show available commands")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📜 Bot Commands",
        description="Here are the available commands:",
        color=0x00FFFF
    )
    embed.add_field(name="/challenge", value="1v1 mode for the leaderboard", inline=False)
    embed.add_field(name="/leaderboard", value="Show leaderboard", inline=False)
    embed.add_field(name="/reset_leaderboard", value="Resets leaderboard", inline=False)
    embed.add_field(name="/tournament", value="Forms a tournament bracket for 4, 8, or 16 players", inline=False)
    embed.set_footer(text="Use these commands to compete and track scores!")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

client.run(os.environ.get("DISCORD_KEY"))





