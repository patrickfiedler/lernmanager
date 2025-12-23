/**
 * Boot Scene - Load assets and initialize game
 */

class BootScene extends Phaser.Scene {
    constructor() {
        super({ key: 'BootScene' });
    }

    preload() {
        // Show loading text
        const width = this.cameras.main.width;
        const height = this.cameras.main.height;

        const loadingText = this.add.text(width / 2, height / 2, 'Laden...', {
            fontSize: '24px',
            fill: '#ffffff'
        }).setOrigin(0.5);

        // Create placeholder graphics
        this.createPlaceholderSprites();
    }

    createPlaceholderSprites() {
        const graphics = this.make.graphics({ x: 0, y: 0, add: false });

        // Player sprite (32x48 blue character)
        graphics.fillStyle(GAME_CONFIG.COLORS.PLAYER);
        graphics.fillRect(0, 0, 32, 48);
        graphics.fillStyle(0xffffff);
        graphics.fillRect(8, 8, 6, 6); // Left eye
        graphics.fillRect(18, 8, 6, 6); // Right eye
        graphics.generateTexture('player', 32, 48);
        graphics.clear();

        // Monster sprite (40x40 red enemy)
        graphics.fillStyle(GAME_CONFIG.COLORS.MONSTER);
        graphics.fillRect(0, 0, 40, 40);
        graphics.fillStyle(0xffffff);
        graphics.fillRect(8, 10, 8, 8);
        graphics.fillRect(24, 10, 8, 8);
        graphics.fillStyle(0x000000);
        graphics.fillRect(10, 12, 4, 4);
        graphics.fillRect(26, 12, 4, 4);
        graphics.generateTexture('monster', 40, 40);
        graphics.clear();

        // NPC sprite (32x48 yellow)
        graphics.fillStyle(GAME_CONFIG.COLORS.NPC);
        graphics.fillRect(0, 0, 32, 48);
        graphics.fillStyle(0x000000);
        graphics.fillRect(8, 8, 6, 6);
        graphics.fillRect(18, 8, 6, 6);
        graphics.generateTexture('npc', 32, 48);
        graphics.clear();

        // Grass tile (64x32 isometric)
        graphics.fillStyle(GAME_CONFIG.COLORS.GRASS);
        graphics.beginPath();
        graphics.moveTo(32, 0);
        graphics.lineTo(64, 16);
        graphics.lineTo(32, 32);
        graphics.lineTo(0, 16);
        graphics.closePath();
        graphics.fillPath();
        graphics.lineStyle(1, 0x166534);
        graphics.strokePath();
        graphics.generateTexture('tile_grass', 64, 32);
        graphics.clear();

        // Dirt tile
        graphics.fillStyle(GAME_CONFIG.COLORS.DIRT);
        graphics.beginPath();
        graphics.moveTo(32, 0);
        graphics.lineTo(64, 16);
        graphics.lineTo(32, 32);
        graphics.lineTo(0, 16);
        graphics.closePath();
        graphics.fillPath();
        graphics.lineStyle(1, 0xa3845a);
        graphics.strokePath();
        graphics.generateTexture('tile_dirt', 64, 32);
        graphics.clear();

        // Stone tile
        graphics.fillStyle(GAME_CONFIG.COLORS.STONE);
        graphics.beginPath();
        graphics.moveTo(32, 0);
        graphics.lineTo(64, 16);
        graphics.lineTo(32, 32);
        graphics.lineTo(0, 16);
        graphics.closePath();
        graphics.fillPath();
        graphics.lineStyle(1, 0x64748b);
        graphics.strokePath();
        graphics.generateTexture('tile_stone', 64, 32);
        graphics.clear();

        // Dark tile (for caves)
        graphics.fillStyle(GAME_CONFIG.COLORS.STONE);
        graphics.beginPath();
        graphics.moveTo(32, 0);
        graphics.lineTo(64, 16);
        graphics.lineTo(32, 32);
        graphics.lineTo(0, 16);
        graphics.closePath();
        graphics.fillPath();
        graphics.fillStyle(0x000000, 0.3);
        graphics.fillPath();
        graphics.generateTexture('tile_dark', 64, 32);
        graphics.clear();

        // Tree (simple triangle)
        graphics.fillStyle(GAME_CONFIG.COLORS.TREE);
        graphics.beginPath();
        graphics.moveTo(16, 0);
        graphics.lineTo(32, 40);
        graphics.lineTo(0, 40);
        graphics.closePath();
        graphics.fillPath();
        graphics.fillStyle(0x8b5a2b);
        graphics.fillRect(12, 40, 8, 16);
        graphics.generateTexture('tree', 32, 56);
        graphics.clear();

        // Building (simple house shape)
        graphics.fillStyle(GAME_CONFIG.COLORS.BUILDING);
        graphics.fillRect(0, 20, 48, 36);
        graphics.fillStyle(0x8b4513);
        graphics.beginPath();
        graphics.moveTo(24, 0);
        graphics.lineTo(48, 20);
        graphics.lineTo(0, 20);
        graphics.closePath();
        graphics.fillPath();
        graphics.fillStyle(0x654321);
        graphics.fillRect(18, 36, 12, 20);
        graphics.generateTexture('building', 48, 56);
        graphics.clear();

        // Exit portal
        graphics.fillStyle(0x8b5cf6);
        graphics.fillCircle(20, 20, 18);
        graphics.fillStyle(0xc4b5fd);
        graphics.fillCircle(20, 20, 12);
        graphics.fillStyle(0xffffff);
        graphics.fillCircle(20, 20, 6);
        graphics.generateTexture('portal', 40, 40);
        graphics.clear();

        graphics.destroy();
    }

    create() {
        // Start the village scene
        const startArea = window.GAME_DATA.character.current_area || 'village';

        if (startArea === 'village') {
            this.scene.start('VillageScene');
        } else {
            this.scene.start('ExplorationScene', { area: startArea });
        }
    }
}

// Export
if (typeof window !== 'undefined') {
    window.BootScene = BootScene;
}
