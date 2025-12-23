/**
 * Combat Scene - Quiz-based monster battles
 */

class CombatScene extends Phaser.Scene {
    constructor() {
        super({ key: 'CombatScene' });
    }

    init(data) {
        this.returnArea = data.area || 'meadow';
        this.monsterName = data.monster || 'Monster';
        this.difficulty = data.difficulty || 1;
        this.correctAnswers = 0;
        this.currentQuestion = null;
    }

    create() {
        this.createBackground();
        this.createMonster();
        this.createUI();

        // Load first question
        this.loadQuestion();
    }

    createBackground() {
        // Dark battle background
        this.add.rectangle(
            GAME_CONFIG.WIDTH / 2,
            GAME_CONFIG.HEIGHT / 2,
            GAME_CONFIG.WIDTH,
            GAME_CONFIG.HEIGHT,
            0x1a1a2e
        );

        // Battle arena floor
        this.add.ellipse(
            GAME_CONFIG.WIDTH / 2,
            GAME_CONFIG.HEIGHT - 150,
            400,
            100,
            0x2d3748
        );
    }

    createMonster() {
        // Monster sprite
        this.monster = this.add.sprite(
            GAME_CONFIG.WIDTH / 2,
            GAME_CONFIG.HEIGHT / 2 - 50,
            'monster'
        );
        this.monster.setScale(3);

        // Monster name
        this.add.text(GAME_CONFIG.WIDTH / 2, 80, this.monsterName, {
            fontSize: '32px',
            fill: '#ef4444',
            stroke: '#000000',
            strokeThickness: 4
        }).setOrigin(0.5);

        // Health indicators (questions remaining)
        this.createHealthIndicators();

        // Idle animation
        this.tweens.add({
            targets: this.monster,
            y: this.monster.y - 10,
            duration: 1000,
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut'
        });
    }

    createHealthIndicators() {
        this.healthIndicators = [];
        const startX = GAME_CONFIG.WIDTH / 2 - 40;

        for (let i = 0; i < GAME_CONFIG.QUESTIONS_TO_WIN; i++) {
            const indicator = this.add.circle(
                startX + i * 30,
                130,
                10,
                0xef4444
            );
            indicator.setStrokeStyle(2, 0xffffff);
            this.healthIndicators.push(indicator);
        }
    }

    updateHealthIndicators() {
        for (let i = 0; i < this.correctAnswers; i++) {
            if (this.healthIndicators[i]) {
                this.healthIndicators[i].setFillStyle(0x22c55e);
            }
        }
    }

    createUI() {
        // Instructions
        this.add.text(GAME_CONFIG.WIDTH / 2, GAME_CONFIG.HEIGHT - 50, 'Beantworte die Frage um anzugreifen!', {
            fontSize: '16px',
            fill: '#94a3b8'
        }).setOrigin(0.5);
    }

    async loadQuestion() {
        try {
            this.currentQuestion = await GameAPI.getQuestion();
            QuestionPanel.show(this.currentQuestion, this.monsterName, (answer) => {
                this.submitAnswer(answer);
            });
        } catch (error) {
            console.error('Failed to load question:', error);
            // Return to exploration on error
            this.scene.start('ExplorationScene', { area: this.returnArea });
        }
    }

    async submitAnswer(selectedIndices) {
        if (!this.currentQuestion) return;

        try {
            const result = await GameAPI.submitAnswer(
                this.currentQuestion.question_id,
                selectedIndices,
                this.currentQuestion.source
            );

            QuestionPanel.hide();

            if (result.correct) {
                this.handleCorrectAnswer(result);
            } else {
                this.handleIncorrectAnswer(result);
            }
        } catch (error) {
            console.error('Failed to submit answer:', error);
        }
    }

    handleCorrectAnswer(result) {
        this.correctAnswers++;
        this.updateHealthIndicators();

        // Update HUD
        if (result.xp_gained) {
            HUD.addXP(result.xp_gained);
        }

        // Show result
        this.showResult(true, result);

        // Monster hit animation
        this.tweens.add({
            targets: this.monster,
            alpha: 0.5,
            duration: 100,
            yoyo: true,
            repeat: 2
        });

        // Check for victory
        if (this.correctAnswers >= GAME_CONFIG.QUESTIONS_TO_WIN) {
            this.time.delayedCall(1500, () => this.handleVictory(result));
        } else {
            this.time.delayedCall(1500, () => this.loadQuestion());
        }

        // Check for level up
        if (result.level_up) {
            this.time.delayedCall(500, () => {
                this.showLevelUp(result.new_level);
            });
        }
    }

    handleIncorrectAnswer(result) {
        // Update HUD
        HUD.updateHP(result.new_hp, window.GAME_DATA.character.max_hp);

        // Show result with correct answer
        this.showResult(false, result);

        // Check for defeat
        if (result.defeated) {
            this.time.delayedCall(1500, () => this.handleDefeat());
        } else {
            this.time.delayedCall(2000, () => this.loadQuestion());
        }
    }

    showResult(correct, result) {
        const panel = document.getElementById('result-panel');
        const content = panel.querySelector('.result-content');
        const icon = document.getElementById('result-icon');
        const text = document.getElementById('result-text');
        const details = document.getElementById('result-details');

        content.className = 'result-content ' + (correct ? 'correct' : 'incorrect');
        icon.textContent = correct ? '✅' : '❌';
        text.textContent = correct ? 'Richtig!' : 'Falsch!';

        if (correct) {
            details.textContent = `+${result.xp_gained} XP`;
        } else {
            details.textContent = `${result.hp_change} HP`;
        }

        panel.classList.remove('hidden');

        // Auto-hide after delay
        setTimeout(() => {
            panel.classList.add('hidden');
        }, 1400);
    }

    showLevelUp(newLevel) {
        const panel = document.getElementById('levelup-panel');
        document.getElementById('new-level').textContent = `Level ${newLevel}`;
        panel.classList.remove('hidden');

        document.getElementById('levelup-continue').onclick = () => {
            panel.classList.add('hidden');
        };
    }

    handleVictory(result) {
        // Victory message
        const victoryText = this.add.text(
            GAME_CONFIG.WIDTH / 2,
            GAME_CONFIG.HEIGHT / 2,
            'Sieg!',
            {
                fontSize: '64px',
                fill: '#22c55e',
                stroke: '#000000',
                strokeThickness: 6
            }
        ).setOrigin(0.5);

        // Monster death animation
        this.tweens.add({
            targets: this.monster,
            alpha: 0,
            scale: 0,
            duration: 500
        });

        // Check task progress
        if (result.task_progress) {
            this.time.delayedCall(1000, () => {
                this.showTaskProgress(result.task_progress);
            });
        }

        // Return to exploration
        this.time.delayedCall(2500, () => {
            this.scene.start('ExplorationScene', { area: this.returnArea });
        });
    }

    showTaskProgress(progress) {
        const text = `Aufgabe: ${progress.questions_answered}/${progress.questions_total} Fragen`;
        const progressText = this.add.text(
            GAME_CONFIG.WIDTH / 2,
            GAME_CONFIG.HEIGHT / 2 + 80,
            text,
            {
                fontSize: '20px',
                fill: '#60a5fa',
                stroke: '#000000',
                strokeThickness: 3
            }
        ).setOrigin(0.5);

        if (progress.can_complete) {
            this.add.text(
                GAME_CONFIG.WIDTH / 2,
                GAME_CONFIG.HEIGHT / 2 + 110,
                'Aufgabe kann abgeschlossen werden!',
                {
                    fontSize: '16px',
                    fill: '#4ade80',
                    stroke: '#000000',
                    strokeThickness: 2
                }
            ).setOrigin(0.5);
        }
    }

    async handleDefeat() {
        const panel = document.getElementById('defeat-panel');
        panel.classList.remove('hidden');

        document.getElementById('defeat-continue').onclick = async () => {
            panel.classList.add('hidden');

            // Return to village
            await GameAPI.returnToVillage();

            // Update HUD
            const state = await GameAPI.getState();
            HUD.updateHP(state.character.hp, state.character.max_hp);

            this.scene.start('VillageScene');
        };
    }
}

// Export
if (typeof window !== 'undefined') {
    window.CombatScene = CombatScene;
}
