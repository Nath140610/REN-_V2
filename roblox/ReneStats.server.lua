--!strict
-- Script serveur « ReneStats » à placer dans ServerScriptService (type Script, pas ModuleScript).
-- Il envoie au panel René la liste des joueurs de ce serveur :
--   * toutes les minutes ;
--   * quelques secondes après l'arrivée d'un joueur ;
--   * au départ d'un joueur (sa dernière minute de jeu est comptée) ;
--   * à la fermeture du serveur.
-- Le panel affiche alors les serveurs en ligne (même privés), les joueurs uniques et nouveaux,
-- le temps de jeu, les sessions et les joueurs les plus actifs (Statistiques > Jeu Roblox).
--
-- Prérequis : Game Settings > Security > Allow HTTP Requests = activé.
-- Clé : le même secret « rene_api_key » que ReneGiftCodes (ou colle la clé dans FALLBACK_KEY).
-- Indépendant de ReneGiftCodes : il marche seul, même sans codes cadeau.

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")

local BASE_URL = "https://ton-service.onrender.com" -- URL du panel René, sans / final
local FALLBACK_KEY = "" -- clé affichée dans Réglages > Roblox (laisser vide si tu utilises le secret)
local GAME = "christmasrun" -- "pointnemo" dans PointNemo, "christmasrun" dans ChristmasRun
local EVERY = 60 -- secondes entre deux envois
local SEND_IN_STUDIO = true -- false pour ne pas compter les tests dans Studio

if RunService:IsStudio() and not SEND_IN_STUDIO then
	return
end

local function apiKey(): string?
	if FALLBACK_KEY ~= "" then
		return FALLBACK_KEY
	end
	local ok, secret = pcall(function()
		return HttpService:GetSecret("rene_api_key")
	end)
	return if ok then secret :: any else nil
end

local KEY = apiKey()
if KEY == nil then
	warn("[ReneStats] Clé René absente : ajoute le secret rene_api_key ou remplis FALLBACK_KEY.")
	return
end

local JOB_ID = if game.JobId ~= "" then game.JobId else "studio"
local warned = false

local function playerList(except: Player?): { { id: string, name: string } }
	local list = {}
	for _, player in Players:GetPlayers() do
		if player ~= except then
			table.insert(list, { id = tostring(player.UserId), name = player.Name })
		end
	end
	return list
end

local function send(players: { { id: string, name: string } }, left: { string }, closing: boolean)
	local ok, response = pcall(function()
		return HttpService:RequestAsync({
			Url = BASE_URL .. "/api/roblox/heartbeat",
			Method = "POST",
			Headers = { ["X-Rene-Key"] = KEY :: any, ["Content-Type"] = "application/json" },
			Body = HttpService:JSONEncode({
				game = GAME,
				job_id = JOB_ID,
				place_id = tostring(game.PlaceId),
				private = game.PrivateServerId ~= "",
				max_players = Players.MaxPlayers,
				players = players,
				left = left,
				closing = closing,
			}),
		})
	end)
	if not warned and (not ok or not response.Success) then
		-- Un seul avertissement par serveur pour ne pas remplir la console.
		warned = true
		warn("[ReneStats] René ne répond pas :", if ok then response.StatusCode .. " " .. response.Body else response)
	end
end

-- Arrivée : un seul envoi pour plusieurs joueurs qui arrivent en même temps.
local pending = false
Players.PlayerAdded:Connect(function()
	if pending then
		return
	end
	pending = true
	task.delay(5, function()
		pending = false
		send(playerList(), {}, false)
	end)
end)

-- Départ : le joueur qui part est signalé pour compter son temps jusqu'à maintenant.
Players.PlayerRemoving:Connect(function(player)
	task.spawn(send, playerList(player), { tostring(player.UserId) }, false)
end)

-- Fermeture du serveur : tout le monde part.
game:BindToClose(function()
	local left = {}
	for _, item in playerList() do
		table.insert(left, item.id)
	end
	send({}, left, true)
end)

-- Envoi régulier.
while true do
	send(playerList(), {}, false)
	task.wait(EVERY)
end
