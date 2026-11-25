-- Script serveur d'exemple : un joueur envoie un code depuis son interface (RemoteFunction « RedeemGiftCode »
-- dans ReplicatedStorage) et le serveur le vérifie auprès de René avant de donner la récompense.

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")
local Codes = require(ServerScriptService.ReneGiftCodes)

local remote = Instance.new("RemoteFunction")
remote.Name = "RedeemGiftCode"
remote.Parent = ReplicatedStorage

local MESSAGES = {
	inactive = "Gratte d'abord ta carte cadeau.",
	used = "Ce code a déjà été utilisé.",
	expired = "Ce code a expiré.",
	replaced = "Ce code a été remplacé : utilise ta nouvelle carte.",
	unknown = "Code inconnu.",
	error = "René ne répond pas. Réessaie dans un instant.",
}

local cooldown: { [number]: number } = {}

local function giveReward(player: Player)
	-- Mets ici ta récompense (monnaie, objet, badge…).
	print(player.Name .. " reçoit sa récompense.")
end

remote.OnServerInvoke = function(player: Player, code: any)
	if typeof(code) ~= "string" or #code > 30 then
		return false, MESSAGES.unknown
	end
	if os.clock() - (cooldown[player.UserId] or 0) < 3 then
		return false, "Patiente quelques secondes."
	end
	cooldown[player.UserId] = os.clock()

	local ok, info = Codes.redeem(code, player)
	if ok then
		giveReward(player)
		return true, "Code validé !"
	end
	return false, MESSAGES[info.status] or MESSAGES.error
end
