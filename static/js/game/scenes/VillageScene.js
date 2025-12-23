/**
 * Village Scene - Safe hub area
 */

class VillageScene extends Phaser.Scene {
    constructor() {
        super({ key: 'VillageScene' });
    }

    create() {
        this.createMap();
        this.createPlayer();
        this.createNPCs();
        this.createExits();
        this.setupControls();
        this.setupCamera();

        // Update HUD
        HUD.updateArea('Startdorf');

        // Update backend
        GameAPI.move('village', 0, 0);
    }

    createMap() {
        const mapSize = GAME_CONFIG.AREAS.village.mapSize;
        const tileW = GAME_CONFIG.TILE_WIDTH;
        const tileH = GAME_CONFIG.TILE_HEIGHT;

        // Center offset
        const offsetX = GAME_CONFIG.WIDTH / 2;
        const offsetY = 100;

        this.tiles = this.add.group();

        // Create isometric grid
        for (let y = 0; y < mapSize.height; y++) {
            for (let x = 0; x < mapSize.width; x++) {
                // Convert to isometric
                const isoX = (x - y) * (tileW / 2) + offsetX;
                const isoY = (x + y) * (tileH / 2) + offsetY;

                // Choose tile type
                let tileKey = 'tile_grass';
                if ((x === 7 && y >= 5 && y <= 9) || (y === 7 && x >= 5 && x <= 9)) {
                    tileKey = 'tile_dirt'; // Path
                }

                const tile = this.add.image(isoX, isoY, tileKey);
                tile.setDepth(y);
                this.tiles.add(tile);
            }
        }

        // Add buildings
        this.add.image(offsetX - 100, offsetY + 180, 'building').setDepth(100);
        this.add.image(offsetX + 100, offsetY + 180, 'building').setDepth(100);

        // Add some trees
        this.add.image(offsetX - 200, offsetY + 100, 'tree').setDepth(50);
        this.add.image(offsetX + 200, offsetY + 100, 'tree').setDepth(50);
        this.add.image(offsetX - 180, offsetY + 250, 'tree').setDepth(150);
        this.add.image(offsetX + 180, offsetY + 250, 'tree').setDepth(150);

        // Village name
        this.add.text(GAME_CONFIG.WIDTH / 2, 60, 'Startdorf', {
            fontSize: '28px',
            fill: '#ffffff',
            stroke: '#000000',
            strokeThickness: 4
        }).setOrigin(0.5).setDepth(1000);
    }

    createPlayer() {
        this.player = this.add.sprite(GAME_CONFIG.WIDTH / 2, GAME_CONFIG.HEIGHT / 2, 'player');
        this.player.setDepth(500);

        // Player position in grid coordinates
        this.playerGridX = 7;
        this.playerGridY = 7;
    }

    createNPCs() {
        // Healer NPC
        const healerX = GAME_CONFIG.WIDTH / 2 - 60;
        const healerY = GAME_CONFIG.HEIGHT / 2 - 40;

        this.healer = this.add.sprite(healerX, healerY, 'npc');
        this.healer.setDepth(400);
        this.healer.setInteractive({ useHandCursor: true });

        const healerLabel = this.add.text(healerX, healerY - 40, 'Heiler', {
            fontSize: '14px',
            fill: '#ffffff',
            stroke: '#000000',
            strokeThickness: 2
        }).setOrigin(0.5).setDepth(1000);

        this.healer.on('pointerdown', async () => {
            await this.healPlayer();
        });
    }

    async healPlayer() {
        try {
            const result = await GameAPI.rest();
            HUD.updateHP(result.hp, result.max_hp);

            // Show message
            this.showMessage('HP wiederhergestellt!');
        } catch (error) {
            console.error('Failed to heal:', error);
        }
    }

    showMessage(text) {
        const msg = this.add.text(GAME_CONFIG.WIDTH / 2, GAME_CONFIG.HEIGHT / 2 - 100, text, {
            fontSize: '24px',
            fill: '#4ade80',
            stroke: '#000000',
            strokeThickness: 3
        }).setOrigin(0.5).setDepth(2000);

        this.tweens.add({
            targets: msg,
            y: msg.y - 50,
            alpha: 0,
            duration: 1500,
            onComplete: () => msg.destroy()
        });
    }

    createExits() {
        // Exit to meadow (south)
        const meadowExit = this.add.sprite(GAME_CONFIG.WIDTH / 2, GAME_CONFIG.HEIGHT - 80, 'portal');
        meadowExit.setDepth(1000);
        meadowExit.setInteractive({ useHandCursor: true });

        this.add.text(GAME_CONFIG.WIDTH / 2, GAME_CONFIG.HEIGHT - 40, 'Wiese', {
            fontSize: '16px',
            fill: '#ffffff',
            stroke: '#000000',
            strokeThickness: 2
        }).setOrigin(0.5).setDepth(1000);

        meadowExit.on('pointerdown', () => {
            this.scene.start('ExplorationScene', { area: 'meadow' });
        });

        // Exit to forest (north)
        const forestExit = this.add.sprite(GAME_CONFIG.WIDTH / 2, 120, 'portal');
        forestExit.setDepth(1000);
        forestExit.setInteractive({ useHandCursor: true });

        this.add.text(GAME_CONFIG.WIDTH / 2, 160, 'Wald', {
            fontSize: '16px',
            fill: '#ffffff',
            stroke: '#000000',
            strokeThickness: 2
        }).setOrigin(0.5).setDepth(1000);

        forestExit.on('pointerdown', () => {
            this.scene.start('ExplorationScene', { area: 'forest' });
        });
    }

    setupControls() {
        this.cursors = this.input.keyboard.createCursorKeys();
        this.wasd = this.input.keyboard.addKeys({
            up: Phaser.Input.Keyboard.KeyCodes.W,
            down: Phaser.Input.Keyboard.KeyCodes.S,
            left: Phaser.Input.Keyboard.KeyCodes.A,
            right: Phaser.Input.Keyboard.KeyCodes.D
        });
    }

    setupCamera() {
        // Simple fixed camera for village
    }

    update() {
        // Handle movement
        let dx = 0;
        let dy = 0;

        if (this.cursors.left.isDown || this.wasd.left.isDown) dx = -GAME_CONFIG.PLAYER_SPEED;
        if (this.cursors.right.isDown || this.wasd.right.isDown) dx = GAME_CONFIG.PLAYER_SPEED;
        if (this.cursors.up.isDown || this.wasd.up.isDown) dy = -GAME_CONFIG.PLAYER_SPEED;
        if (this.cursors.down.isDown || this.wasd.down.isDown) dy = GAME_CONFIG.PLAYER_SPEED;

        // Update player position
        const newX = this.player.x + dx;
        const newY = this.player.y + dy;

        // Keep within bounds
        if (newX > 100 && newX < GAME_CONFIG.WIDTH - 100) {
            this.player.x = newX;
        }
        if (newY > 100 && newY < GAME_CONFIG.HEIGHT - 100) {
            this.player.y = newY;
        }
    }
}

// Export
if (typeof window !== 'undefined') {
    window.VillageScene = VillageScene;
}
