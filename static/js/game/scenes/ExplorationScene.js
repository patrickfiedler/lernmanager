/**
 * Exploration Scene - Explorable areas with random encounters
 */

class ExplorationScene extends Phaser.Scene {
    constructor() {
        super({ key: 'ExplorationScene' });
    }

    init(data) {
        this.currentArea = data.area || 'meadow';
        this.areaConfig = GAME_CONFIG.AREAS[this.currentArea];
        this.stepCount = 0;
    }

    create() {
        this.createMap();
        this.createPlayer();
        this.createExits();
        this.setupControls();

        // Update HUD
        HUD.updateArea(this.areaConfig.name);

        // Update backend
        GameAPI.move(this.currentArea, 0, 0);
    }

    createMap() {
        const mapSize = this.areaConfig.mapSize;
        const tileW = GAME_CONFIG.TILE_WIDTH;
        const tileH = GAME_CONFIG.TILE_HEIGHT;

        // Center offset
        const offsetX = GAME_CONFIG.WIDTH / 2;
        const offsetY = 80;

        this.tiles = this.add.group();

        // Choose tile based on area
        let tileKey = 'tile_grass';
        if (this.currentArea === 'forest') tileKey = 'tile_grass';
        if (this.currentArea === 'mountain') tileKey = 'tile_stone';
        if (this.currentArea === 'cave') tileKey = 'tile_dark';

        // Create isometric grid
        for (let y = 0; y < mapSize.height; y++) {
            for (let x = 0; x < mapSize.width; x++) {
                const isoX = (x - y) * (tileW / 2) + offsetX;
                const isoY = (x + y) * (tileH / 2) + offsetY;

                const tile = this.add.image(isoX, isoY, tileKey);
                tile.setDepth(y);
                this.tiles.add(tile);
            }
        }

        // Add decorations based on area
        if (this.currentArea === 'forest' || this.currentArea === 'meadow') {
            // Random trees
            for (let i = 0; i < 15; i++) {
                const tx = Phaser.Math.Between(100, GAME_CONFIG.WIDTH - 100);
                const ty = Phaser.Math.Between(150, GAME_CONFIG.HEIGHT - 150);
                this.add.image(tx, ty, 'tree').setDepth(ty);
            }
        }

        // Area name
        this.add.text(GAME_CONFIG.WIDTH / 2, 40, this.areaConfig.name, {
            fontSize: '24px',
            fill: '#ffffff',
            stroke: '#000000',
            strokeThickness: 4
        }).setOrigin(0.5).setDepth(1000);

        // Warning text for dangerous areas
        if (!this.areaConfig.safe) {
            this.add.text(GAME_CONFIG.WIDTH / 2, 70, '⚠️ Vorsicht: Monster!', {
                fontSize: '14px',
                fill: '#fbbf24',
                stroke: '#000000',
                strokeThickness: 2
            }).setOrigin(0.5).setDepth(1000);
        }
    }

    createPlayer() {
        this.player = this.add.sprite(GAME_CONFIG.WIDTH / 2, GAME_CONFIG.HEIGHT / 2, 'player');
        this.player.setDepth(500);
    }

    createExits() {
        // Get exits for current area
        const exits = {
            village: ['meadow', 'forest'],
            meadow: ['village'],
            forest: ['village', 'mountain', 'cave'],
            mountain: ['forest'],
            cave: ['forest']
        };

        const areaExits = exits[this.currentArea] || ['village'];
        const exitPositions = this.getExitPositions(areaExits.length);

        areaExits.forEach((exitArea, index) => {
            const pos = exitPositions[index];
            const portal = this.add.sprite(pos.x, pos.y, 'portal');
            portal.setDepth(1000);
            portal.setInteractive({ useHandCursor: true });

            const areaName = GAME_CONFIG.AREAS[exitArea]?.name || exitArea;
            this.add.text(pos.x, pos.y + 30, areaName, {
                fontSize: '14px',
                fill: '#ffffff',
                stroke: '#000000',
                strokeThickness: 2
            }).setOrigin(0.5).setDepth(1000);

            portal.on('pointerdown', () => {
                if (exitArea === 'village') {
                    this.scene.start('VillageScene');
                } else {
                    this.scene.start('ExplorationScene', { area: exitArea });
                }
            });
        });
    }

    getExitPositions(count) {
        const positions = [
            { x: GAME_CONFIG.WIDTH / 2, y: GAME_CONFIG.HEIGHT - 60 },
            { x: 80, y: GAME_CONFIG.HEIGHT / 2 },
            { x: GAME_CONFIG.WIDTH - 80, y: GAME_CONFIG.HEIGHT / 2 },
            { x: GAME_CONFIG.WIDTH / 2, y: 100 }
        ];
        return positions.slice(0, count);
    }

    setupControls() {
        this.cursors = this.input.keyboard.createCursorKeys();
        this.wasd = this.input.keyboard.addKeys({
            up: Phaser.Input.Keyboard.KeyCodes.W,
            down: Phaser.Input.Keyboard.KeyCodes.S,
            left: Phaser.Input.Keyboard.KeyCodes.A,
            right: Phaser.Input.Keyboard.KeyCodes.D
        });

        this.lastMoveTime = 0;
    }

    update(time) {
        // Handle movement with encounter check
        let dx = 0;
        let dy = 0;

        if (this.cursors.left.isDown || this.wasd.left.isDown) dx = -GAME_CONFIG.PLAYER_SPEED;
        if (this.cursors.right.isDown || this.wasd.right.isDown) dx = GAME_CONFIG.PLAYER_SPEED;
        if (this.cursors.up.isDown || this.wasd.up.isDown) dy = -GAME_CONFIG.PLAYER_SPEED;
        if (this.cursors.down.isDown || this.wasd.down.isDown) dy = GAME_CONFIG.PLAYER_SPEED;

        if (dx !== 0 || dy !== 0) {
            const newX = Phaser.Math.Clamp(this.player.x + dx, 100, GAME_CONFIG.WIDTH - 100);
            const newY = Phaser.Math.Clamp(this.player.y + dy, 100, GAME_CONFIG.HEIGHT - 100);

            this.player.x = newX;
            this.player.y = newY;

            // Check for encounter every few steps
            if (time - this.lastMoveTime > 200) {
                this.lastMoveTime = time;
                this.stepCount++;

                if (this.stepCount % 5 === 0) {
                    this.checkEncounter();
                }
            }
        }
    }

    async checkEncounter() {
        if (this.areaConfig.safe) return;

        try {
            const result = await GameAPI.move(
                this.currentArea,
                Math.floor(this.player.x),
                Math.floor(this.player.y)
            );

            if (result.encounter) {
                // Start combat scene
                this.scene.start('CombatScene', {
                    area: this.currentArea,
                    monster: result.monster,
                    difficulty: result.area_difficulty
                });
            }
        } catch (error) {
            console.error('Move error:', error);
        }
    }
}

// Export
if (typeof window !== 'undefined') {
    window.ExplorationScene = ExplorationScene;
}
