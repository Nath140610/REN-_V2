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
	no_reward = "Ce code n'est pas encore prêt. Réessaie plus tard.",
	wrong_game = "Ce code est prévu pour un autre jeu.",
	error = "René ne répond pas. Réessaie dans un instant.",
}

local cooldown: { [number]: number } = {}

-- Remplace chaque print par le vrai code de ton jeu.
local function giveReward(player: Player, reward: Codes.Reward)
	if reward.game == "christmasrun" then
		if reward.type == "glings" or reward.type == "glings_gifts" then
			print(player.Name .. " reçoit " .. reward.glings .. " glings")
		end
		if reward.type == "gifts" or reward.type == "glings_gifts" then
			print(player.Name .. " reçoit " .. reward.gifts .. " cadeaux")
		end
		if reward.type == "gamepass_random" then
			print(player.Name .. " reçoit un gamepass au hasard")
		end
	elseif reward.game == "pointnemo" then
		if reward.type == "gamepass_random" then
			print(player.Name .. " reçoit un gamepass au hasard")
		elseif reward.type == "raft_extension" then
			print(player.Name .. " reçoit une extension de radeau")
		elseif reward.type == "server_slot" then
			print(player.Name .. " reçoit un emplacement de serveur en plus")
		end
	end
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
	if ok and info.reward then
		giveReward(player, info.reward)
		return true, "Code validé : " .. info.reward.label
	end
	return false, MESSAGES[info.status] or MESSAGES.error
end
