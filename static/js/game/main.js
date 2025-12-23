/**
 * Main Game Entry Point
 */

// Wait for DOM to be ready
document.addEventListener('DOMContentLoaded', () => {
    // Phaser game configuration
    const config = {
        type: Phaser.AUTO,
        width: GAME_CONFIG.WIDTH,
        height: GAME_CONFIG.HEIGHT,
        parent: 'game-container',
        pixelArt: true,
        backgroundColor: '#1a1a2e',
        scene: [BootScene, VillageScene, ExplorationScene, CombatScene],
        scale: {
            mode: Phaser.Scale.FIT,
            autoCenter: Phaser.Scale.CENTER_BOTH
        }
    };

    // Create game instance
    const game = new Phaser.Game(config);

    // Store reference globally
    window.game = game;

    // Initialize HUD with current data
    if (window.GAME_DATA && window.GAME_DATA.character) {
        const char = window.GAME_DATA.character;
        HUD.updateHP(char.hp, char.max_hp);
        HUD.updateLevel(char.level);
    }

    console.log('Game initialized');
});
