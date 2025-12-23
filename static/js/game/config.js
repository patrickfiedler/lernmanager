/**
 * Game Configuration
 */

const GAME_CONFIG = {
    // Canvas size
    WIDTH: 960,
    HEIGHT: 640,

    // Tile size for isometric grid
    TILE_WIDTH: 64,
    TILE_HEIGHT: 32,

    // Player movement speed
    PLAYER_SPEED: 3,

    // Colors for placeholder graphics
    COLORS: {
        GRASS: 0x4ade80,
        DIRT: 0xd4a574,
        WATER: 0x60a5fa,
        STONE: 0x94a3b8,
        TREE: 0x166534,
        PLAYER: 0x3b82f6,
        MONSTER: 0xef4444,
        NPC: 0xfbbf24,
        BUILDING: 0x78716c
    },

    // Area definitions (matches backend)
    AREAS: {
        village: {
            name: 'Startdorf',
            safe: true,
            color: 0x22c55e,
            mapSize: { width: 15, height: 15 }
        },
        meadow: {
            name: 'Wiese der Anfaenger',
            safe: false,
            color: 0x84cc16,
            mapSize: { width: 20, height: 20 }
        },
        forest: {
            name: 'Wald der Mysterien',
            safe: false,
            color: 0x166534,
            mapSize: { width: 25, height: 25 }
        },
        mountain: {
            name: 'Berg der Herausforderungen',
            safe: false,
            color: 0x78716c,
            mapSize: { width: 20, height: 20 }
        },
        cave: {
            name: 'Hoehle des Wissens',
            safe: false,
            color: 0x44403c,
            mapSize: { width: 18, height: 18 }
        }
    },

    // Monster sprites by difficulty
    MONSTERS: {
        1: ['Schleim', 'Pilzling', 'Nebelwicht'],
        2: ['Waldgeist', 'Schattenkatze', 'Irrwurm'],
        3: ['Felsengolem', 'Dunkelelf', 'Frostwolf'],
        4: ['Sturmdrache', 'Feuerdaemon', 'Schattenlord'],
        5: ['Uralter Wyrm', 'Lichkoenig', 'Chaosbestie']
    },

    // Questions needed to defeat monster
    QUESTIONS_TO_WIN: 3
};

// Export for use in other files
if (typeof window !== 'undefined') {
    window.GAME_CONFIG = GAME_CONFIG;
}
