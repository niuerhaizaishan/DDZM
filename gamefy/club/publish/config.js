export const CONFIG = {
  apiBase: "https://49.234.20.159",
  games: [
    {id: "chess", name: "群聊象棋", path: "./games/chess/index.html?club=1", icon: "象", image: "./assets/game-chess.webp", description: "双人对弈 · 支持观战"},
    {id: "doudizhu", name: "斗地主", path: "./games/doudizhu/index.html?club=1", icon: "斗", image: "./assets/game-doudizhu.webp", description: "经典三人 · 好友牌局"},
    {id: "drawguess", name: "你画我猜", path: "./games/drawguess/index.html?club=1", icon: "画", image: "./assets/game-drawguess.webp", description: "3～8 人 · 轮流作画"},
    {id: "texas", name: "德州扑克", path: "./games/card-table/index.html?club=1&game=texas", icon: "德", image: "./assets/game-texas-table-v1.webp", description: "2～8 人 · 连续牌桌"},
    {id: "zhajinhua", name: "炸金花", path: "./games/card-table/index.html?club=1&game=zhajinhua", icon: "金", image: "./assets/game-zhajinhua-table-v1.webp", description: "2～6 人 · 看牌比牌"},
    {id: "blackjack", name: "21 点", path: "./games/card-table/index.html?club=1&game=blackjack", icon: "21", image: "./assets/game-blackjack-table-v1.webp", description: "2～5 人 · PvP 点数对决"},
  ],
};
