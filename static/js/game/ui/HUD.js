/**
 * HUD - Heads-up display manager
 */

const HUD = {
    /**
     * Update HP display
     */
    updateHP(current, max) {
        const fill = document.getElementById('hp-fill');
        const value = document.getElementById('hp-value');

        if (fill && value) {
            const percent = Math.max(0, Math.min(100, (current / max) * 100));
            fill.style.width = percent + '%';
            value.textContent = `${current}/${max}`;

            // Color based on health
            if (percent > 50) {
                fill.style.background = 'linear-gradient(to bottom, #4ade80, #16a34a)';
            } else if (percent > 25) {
                fill.style.background = 'linear-gradient(to bottom, #fbbf24, #d97706)';
            } else {
                fill.style.background = 'linear-gradient(to bottom, #ef4444, #dc2626)';
            }
        }

        // Update game data
        if (window.GAME_DATA && window.GAME_DATA.character) {
            window.GAME_DATA.character.hp = current;
            window.GAME_DATA.character.max_hp = max;
        }
    },

    /**
     * Update XP display
     */
    updateXP(current, toNext) {
        const fill = document.getElementById('xp-fill');
        const value = document.getElementById('xp-value');

        if (fill && value) {
            // Calculate progress to next level
            const percent = toNext > 0 ? Math.min(100, ((current % 100) / 100) * 100) : 100;
            fill.style.width = percent + '%';
            value.textContent = current;
        }

        // Update game data
        if (window.GAME_DATA && window.GAME_DATA.character) {
            window.GAME_DATA.character.xp = current;
        }
    },

    /**
     * Add XP with animation
     */
    addXP(amount) {
        const value = document.getElementById('xp-value');
        if (value) {
            const current = parseInt(value.textContent) || 0;
            const newXP = current + amount;
            value.textContent = newXP;

            // Flash effect
            value.style.color = '#4ade80';
            setTimeout(() => {
                value.style.color = '';
            }, 500);
        }
    },

    /**
     * Update level display
     */
    updateLevel(level) {
        const levelEl = document.querySelector('.hud-level');
        if (levelEl) {
            levelEl.textContent = `Level ${level}`;
        }

        // Update game data
        if (window.GAME_DATA && window.GAME_DATA.character) {
            window.GAME_DATA.character.level = level;
        }
    },

    /**
     * Update current area display
     */
    updateArea(areaName) {
        const areaEl = document.getElementById('current-area');
        if (areaEl) {
            areaEl.textContent = areaName;
        }
    },

    /**
     * Refresh all HUD elements from game state
     */
    async refresh() {
        try {
            const state = await GameAPI.getState();

            this.updateHP(state.character.hp, state.character.max_hp);
            this.updateXP(state.character.xp, state.character.xp_to_next);
            this.updateLevel(state.character.level);

            const areaName = GAME_CONFIG.AREAS[state.character.area]?.name || state.character.area;
            this.updateArea(areaName);

            // Update global game data
            window.GAME_DATA.character = state.character;
        } catch (error) {
            console.error('Failed to refresh HUD:', error);
        }
    }
};

// Export
if (typeof window !== 'undefined') {
    window.HUD = HUD;
}
