/**
 * Question Panel - Quiz UI for combat
 */

const QuestionPanel = {
    selectedAnswers: [],
    currentQuestion: null,
    onSubmitCallback: null,

    /**
     * Show question panel with a question
     */
    show(question, monsterName, onSubmit) {
        this.currentQuestion = question;
        this.selectedAnswers = [];
        this.onSubmitCallback = onSubmit;

        const panel = document.getElementById('question-panel');
        const monsterNameEl = document.getElementById('monster-name');
        const sourceEl = document.getElementById('question-source');
        const textEl = document.getElementById('question-text');
        const answersEl = document.getElementById('answers-container');
        const submitBtn = document.getElementById('submit-answer');

        // Set content
        monsterNameEl.textContent = monsterName;

        // Source label
        const sourceLabels = {
            'current_task': 'Aktuelle Aufgabe',
            'repetition': 'Wiederholung',
            'random': 'Zufaellig'
        };
        sourceEl.textContent = sourceLabels[question.source] || '';

        textEl.textContent = question.text;

        // Clear and create answer options
        answersEl.innerHTML = '';
        question.answers.forEach((answer, index) => {
            const option = document.createElement('div');
            option.className = 'answer-option';
            option.dataset.index = index;
            option.innerHTML = `
                <div class="checkbox"></div>
                <span>${answer}</span>
            `;
            option.addEventListener('click', () => this.toggleAnswer(index, question.multiple));
            answersEl.appendChild(option);
        });

        // Setup submit button
        submitBtn.disabled = true;
        submitBtn.onclick = () => this.submit();

        // Show hint for multiple answers
        if (question.multiple) {
            const hint = document.createElement('div');
            hint.className = 'question-hint';
            hint.style.cssText = 'color: #60a5fa; font-size: 14px; margin-bottom: 10px;';
            hint.textContent = 'Mehrere Antworten moeglich';
            answersEl.insertBefore(hint, answersEl.firstChild);
        }

        // Show panel
        panel.classList.remove('hidden');
    },

    /**
     * Toggle answer selection
     */
    toggleAnswer(index, allowMultiple) {
        const answersEl = document.getElementById('answers-container');
        const options = answersEl.querySelectorAll('.answer-option');

        if (allowMultiple) {
            // Toggle this answer
            const idx = this.selectedAnswers.indexOf(index);
            if (idx > -1) {
                this.selectedAnswers.splice(idx, 1);
                options[index].classList.remove('selected');
            } else {
                this.selectedAnswers.push(index);
                options[index].classList.add('selected');
            }
        } else {
            // Single selection - clear others
            this.selectedAnswers = [index];
            options.forEach((opt, i) => {
                opt.classList.toggle('selected', i === index);
            });
        }

        // Enable submit if at least one answer selected
        const submitBtn = document.getElementById('submit-answer');
        submitBtn.disabled = this.selectedAnswers.length === 0;
    },

    /**
     * Submit the answer
     */
    submit() {
        if (this.selectedAnswers.length === 0) return;

        const submitBtn = document.getElementById('submit-answer');
        submitBtn.disabled = true;

        if (this.onSubmitCallback) {
            this.onSubmitCallback(this.selectedAnswers);
        }
    },

    /**
     * Hide the question panel
     */
    hide() {
        const panel = document.getElementById('question-panel');
        panel.classList.add('hidden');
        this.currentQuestion = null;
        this.selectedAnswers = [];
    },

    /**
     * Show correct answer feedback
     */
    showCorrectAnswers(correctIndices) {
        const answersEl = document.getElementById('answers-container');
        const options = answersEl.querySelectorAll('.answer-option');

        options.forEach((opt, index) => {
            if (correctIndices.includes(index)) {
                opt.style.borderColor = '#22c55e';
                opt.style.background = 'rgba(34, 197, 94, 0.2)';
            }
        });
    }
};

// Export
if (typeof window !== 'undefined') {
    window.QuestionPanel = QuestionPanel;
}
