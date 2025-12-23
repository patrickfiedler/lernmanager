/**
 * Game API Wrapper
 */

const GameAPI = {
    /**
     * Get current game state
     */
    async getState() {
        const response = await fetch('/api/game/state');
        if (!response.ok) throw new Error('Failed to get game state');
        return response.json();
    },

    /**
     * Move player and check for encounters
     */
    async move(area, x, y) {
        const response = await fetch('/api/game/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ area, x, y })
        });
        if (!response.ok) throw new Error('Failed to move');
        return response.json();
    },

    /**
     * Get a question for encounter
     */
    async getQuestion() {
        const response = await fetch('/api/game/encounter/question');
        if (!response.ok) throw new Error('Failed to get question');
        return response.json();
    },

    /**
     * Submit answer
     */
    async submitAnswer(questionId, answerIndices, source) {
        const response = await fetch('/api/game/encounter/answer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question_id: questionId,
                answer_indices: answerIndices,
                source: source
            })
        });
        if (!response.ok) throw new Error('Failed to submit answer');
        return response.json();
    },

    /**
     * Rest at village
     */
    async rest() {
        const response = await fetch('/api/game/village/rest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (!response.ok) throw new Error('Failed to rest');
        return response.json();
    },

    /**
     * Return to village after defeat
     */
    async returnToVillage() {
        const response = await fetch('/api/game/village/return', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (!response.ok) throw new Error('Failed to return');
        return response.json();
    },

    /**
     * Sync question pool
     */
    async syncQuestions() {
        const response = await fetch('/api/game/sync-questions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (!response.ok) throw new Error('Failed to sync');
        return response.json();
    }
};

// Export for use in other files
if (typeof window !== 'undefined') {
    window.GameAPI = GameAPI;
}
