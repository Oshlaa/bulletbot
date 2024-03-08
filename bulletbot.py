#    Copyright (C) 2024, oshla <oshla@osh.la>

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
import random
import string
import aiohttp
import interactions
import yaml

bot = interactions.Client(intents=interactions.Intents.DEFAULT, send_command_tracebacks=True)


def random_string(length: int, type=string.ascii_letters):
    return ''.join(random.choices(type, k=length))

def get_yaml(filename: str):
    with open(str(filename)) as file:
        yaml_data = yaml.load(file, Loader=yaml.SafeLoader)
    return yaml_data




global tourneys
tourneys = {}
config_data = get_yaml("config.yml")
challonge_api_url = "https://api.challonge.com"
challonge_api_key = config_data["challonge-api-key"]
allowed_roles = config_data["allowed-roles"]
command_server_scopes = config_data["command-scopes"]



async def challonge_post(json: dict, path: str):

    async with aiohttp.ClientSession(base_url=challonge_api_url, headers={'User-Agent': 'BulletBot'}) as session:
    
        async with session.post(path, json=json) as r:

            if r.status != 200:
                print(f"\nRequest to {path} failed with status {str(r.status)}\n{'-'*20}\n{r.text}\n{'-'*20}")
                raise RuntimeError
            else:
                return await r.json()




def create_tourney_teams(players: dict, players_per_team: int):
    #check if players is evenly divisible by players_per_team and that there is more than 1 team available
    if len(players) % players_per_team != 0 or len(players)/players_per_team < 2:
        raise ValueError


    id_teams = []
    challonge_teams = []


    for _ in range(len(players)//players_per_team):
        id_team = []
        challonge_team = []

        for _ in range(players_per_team):
            player = players.pop(random.randrange(len(players)))
            id_team.append(player["id"])
            challonge_team.append(player["name"])
        

        id_teams.append(id_team)
        challonge_teams.append(" ".join(challonge_team))

    return {"ids": id_teams, "teams": challonge_teams}




async def create_challonge_tourney(teams, name):
    creation_json = {
    "api_key": challonge_api_key,
    "tournament": {
        "name": name,
        "ranked_by": "game wins",
        "signup_cap": 100,
        "start_at": "2025-01-01T00:00:00+0000",
        "check_in_duration": 10,
        "url": f"{random_string(20)}",
        "description": "Bracket automatically created by Oshla's bullet bot",
        "open_signup": False,
        "subdomain": ""
        }
    }


    challonge_teams = []
    for team in teams:
        challonge_teams.append({'name': team})


    team_add_json = {
        "api_key": challonge_api_key,
        "participants": challonge_teams
    }


    tourney_create_request = await challonge_post(json=creation_json, path="/v1/tournaments.json")


    tourney_id = tourney_create_request["tournament"]["id"]
    tourney_url = tourney_create_request["tournament"]["full_challonge_url"]


    await challonge_post(json=team_add_json, path=f"/v1/tournaments/{tourney_id}/participants/bulk_add.json")

    return tourney_url





@interactions.listen() 
async def on_ready():
    print("Ready")






@interactions.slash_command(name="bullet", description="Create a bullet tournament", scopes=command_server_scopes)
@interactions.slash_option(
    name="move",
    description="Automatically move all players into separate voice channels",
    required=True,
    opt_type=interactions.OptionType.BOOLEAN,
)
@interactions.slash_option(
    name="type",
    description="Tourney type (1v1, 2v2, 3v3, etc.)",
    required=True,
    opt_type=interactions.OptionType.INTEGER,
    choices=[
        interactions.SlashCommandChoice(name="1v1", value=1),
        interactions.SlashCommandChoice(name="2v2", value=2),
        interactions.SlashCommandChoice(name="3v3", value=3),
        interactions.SlashCommandChoice(name="4v4", value=4)
    ]
)
async def bullet(ctx: interactions.InteractionContext, move: bool, type: int):
    global tourneys
    
    if ctx.guild.id not in tourneys.keys():
        tourneys[ctx.guild.id] = {"active": False, "delete": False}


    #yes I know this is an idiotic way to check roles/perms but I am too lazy to do it properly
    allow = False
    for role in ctx.author.roles:   
        if role.id in allowed_roles:
            allow = True

    if allow == False:
        await ctx.send("Insufficient permissions :x:", reply_to=ctx.message, ephemeral=True)
        return
    

    if tourneys[ctx.guild.id]["active"] == True:
        await ctx.send("**There is already a bullet running in this server.** Use /bullet_end to end it!", reply_to=ctx.message, ephemeral=True)
        return
    else:
        tourneys[ctx.guild.id]["active"] = True





    players = []
    mentions = []
    for member in ctx.author.voice.channel.voice_members:

        if member.bot != True and member.deaf != True and member.voice.self_deaf != True:

            mentions.append(f"<@{member.id}>")
            players.append({"id": member.id, "name": member.display_name})



    

    try:
        tourney_teams = create_tourney_teams(players=players, players_per_team=type)
    except ValueError:
        await ctx.send("Invalid number of __undeafened__ users in your voice channel :x:", reply_to=ctx.message, ephemeral=True)
        tourneys[ctx.guild.id]["active"] = False
        return
    
    id_teams = tourney_teams["ids"]

    try:
        tourney_url = await create_challonge_tourney(teams=tourney_teams["teams"], name=f"Bullet-{random_string(15)}")
    except Exception as e:
        await ctx.send("API request to Challonge failed :x:", reply_to=ctx.message, ephemeral=True)
        tourneys[ctx.guild.id]["active"] = False
        return



    discord_teams = []

    for team in id_teams:
        users = []

        for id in team:
            users.append(ctx.guild.get_member(id))
        
        discord_teams.append(users)




    bullet_category = await ctx.author.guild.create_category(name=f"{str(type)}v{str(type)} bullet", reason="Temporary category for bullet related channels")
    bullet_bracket_channel = await ctx.author.guild.create_text_channel(name="bracket", category=bullet_category, reason="Temporary bracket channel for the bullet")
    
    await bullet_bracket_channel.send(f"{''.join(mentions)}\nBracket: {tourney_url}")


    team_vcs = []
    pre_bullet_vc = ctx.author.voice.channel.id


    await ctx.send(f"Doubles bracket: <{tourney_url}> (<#{bullet_bracket_channel.id}>)", reply_to=ctx.message)


    if move == True:
        for team in discord_teams:

            temp_team_vc = await ctx.author.guild.create_voice_channel(name=" ".join(user.display_name for user in team), category=bullet_category, reason="Temporary voice channel for bullet team")
            
            team_vcs.append(temp_team_vc)

            for user in team:
                try:
                    await user.move(temp_team_vc.id)
                except:
                    pass

    
    #yeaaaaa I know this is a nasty way to handle this but I just uh I mean uhhhhhh
    while tourneys[ctx.guild.id]["delete"] == False:
        await asyncio.sleep(1)


    for channel in team_vcs:
        try:
            if len(channel.voice_members) > 0:
                for voice_member in channel.voice_members:
                        await voice_member.move(pre_bullet_vc)


            await channel.delete(reason="Cleaning up team channels after bullet")


        except Exception as e:
            print("Could not delete team channel")
            print(e)



    try:
        await bullet_bracket_channel.delete(reason="Cleaning up channels after bullet")
        await bullet_category.delete(reason="Cleaning up channels after bullet")
    except Exception as e:
        print("Could not delete bullet category")
        print(e)

    tourneys[ctx.guild.id]["delete"] = False
    tourneys[ctx.guild.id]["active"] = False







@interactions.slash_command(name="bullet_end", description="End the active bullet tournament in this server", scopes=command_server_scopes)
async def end_bullet(ctx: interactions.InteractionContext):
    global tourneys
    
    if ctx.guild.id not in tourneys.keys():
        tourneys[ctx.guild.id] = {"active": False, "delete": False}


    allow = False
    for role in ctx.author.roles:   
        if role.id in allowed_roles:
            allow = True

    if allow == False:
        await ctx.send("Insufficient permissions :x:", reply_to=ctx.message, ephemeral=True)
        return


    if tourneys[ctx.guild.id]["active"] == True:
        tourneys[ctx.guild.id]["delete"] = True
        await ctx.send("**Bullet ending** :white_check_mark:", reply_to=ctx.message)
        return
    else:
        await ctx.send("**There is no active bullet to end** :x:", reply_to=ctx.message, ephemeral=True)





if __name__ == "__main__":
    bot.start(token=config_data["bot-token"])
