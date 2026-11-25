--!strict
-- ModuleScript « ReneGiftCodes » à placer dans ServerScriptService (jamais côté client).
-- Prérequis : Game Settings > Security > Allow HTTP Requests = activé.
--
-- Clé (recommandé) : secret « rene_api_key », domaine = ton service Render.
--   En ligne : Creator Hub > ton expérience > Secrets > Create Secret.
--   Dans Studio : File > Experience Settings > Security > Local Secrets.
-- Sinon, colle la clé du panel dans FALLBACK_KEY (le script reste côté serveur).
--
-- Utilisation :
--   local Codes = require(game.ServerScriptService.ReneGiftCodes)
--   local info = Codes.check("VOID-AB7K-MP4X-9TQH")      -- info.status, info.available, info.used...
--   local ok, info = Codes.redeem("VOID-AB7K-MP4X-9TQH", player)  -- consomme le code une seule fois

local HttpService = game:GetService("HttpService")

local BASE_URL = "https://ton-service.onrender.com" -- URL du panel René, sans / final
local FALLBACK_KEY = "" -- clé affichée dans Réglages > Roblox (laisser vide si tu utilises le secret)
local GAME = "christmasrun" -- "pointnemo" dans PointNemo, "christmasrun" dans ChristmasRun

local ReneGiftCodes = {}

export type Reward = {
	game: string, -- "pointnemo" | "christmasrun"
	-- PointNemo : "gamepass_random" | "raft_extension" | "server_slot"
	-- ChristmasRun : "glings" | "gifts" | "glings_gifts" | "gamepass_random"
	type: string,
	glings: number?,
	gifts: number?,
	gamepass: boolean,
	label: string,
}

export type CodeInfo = {
	code: string,
	-- "inactive" | "available" | "used" | "expired" | "replaced" | "no_reward" | "wrong_game" | "unknown" | "error"
	status: string,
	label: string?,
	activated: boolean,
	available: boolean,
	used: boolean,
	remaining_seconds: number?,
	recipient_roblox_name: string?,
	used_by_roblox_name: string?,
	game: string?,
	reward: Reward?, -- ce que le joueur doit recevoir
	redeemed: boolean?,
	error: string?,
}

local function apiKey(): any
	if FALLBACK_KEY ~= "" then
		return FALLBACK_KEY
	end
	local ok, secret = pcall(function()
		return HttpService:GetSecret("rene_api_key")
	end)
	return if ok then secret else nil
end

local function request(method: string, path: string, body: { [string]: any }?): CodeInfo
	local key = apiKey()
	if key == nil then
		return { code = "", status = "error", activated = false, available = false, used = false, error = "Clé René absente" }
	end
	local ok, response = pcall(function()
		return HttpService:RequestAsync({
			Url = BASE_URL .. path,
			Method = method,
			Headers = { ["X-Rene-Key"] = key, ["Content-Type"] = "application/json" },
			Body = if body then HttpService:JSONEncode(body) else nil,
		})
	end)
	if not ok then
		return { code = "", status = "error", activated = false, available = false, used = false, error = tostring(response) }
	end
	local decoded, data = pcall(function()
		return HttpService:JSONDecode(response.Body)
	end)
	if not decoded or type(data) ~= "table" then
		return { code = "", status = "error", activated = false, available = false, used = false, error = "Réponse illisible (" .. response.StatusCode .. ")" }
	end
	if data.error and data.status == nil then
		data.status = "error"
		data.activated, data.available, data.used = false, false, false
	end
	return data
end

-- Demande au site si le code est activé, utilisé ou disponible. Ne consomme rien.
function ReneGiftCodes.check(code: string): CodeInfo
	return request("GET", "/api/roblox/code/" .. HttpService:UrlEncode(code) .. "?game=" .. GAME)
end

-- Consomme le code pour ce joueur. Renvoie true une seule fois, même si deux serveurs essaient.
-- Un code sans gain ou prévu pour l'autre jeu est refusé : info.reward dit quoi donner.
function ReneGiftCodes.redeem(code: string, player: Player): (boolean, CodeInfo)
	local info = request("POST", "/api/roblox/redeem", {
		code = code,
		roblox_user_id = tostring(player.UserId),
		roblox_username = player.Name,
		place_id = tostring(game.PlaceId),
		game = GAME,
	})
	return info.redeemed == true, info
end

return ReneGiftCodes
