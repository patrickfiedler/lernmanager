/* Shared "this button is waiting for the server" contract for every button that
 * triggers a graded/AI call (checkpoint quiz, warmup, practice, artifact check).
 *
 * Why this exists: fetch() is invisible. Unlike a form submit it produces no tab
 * spinner and no page-load bar, so a student staring at an unchanged "Prüfen"
 * button cannot tell "the AI is thinking" from "this is broken" -- and clicks
 * again. In a graded checkpoint each extra click used to cost a real point
 * (3 points requires attempts == 1) as well as LLM budget.
 *
 * Guarantees, in order of importance:
 *   1. One click = one request. The busy flag blocks re-entry from any path
 *      (mouse, Enter key, programmatic call), not just pointer clicks.
 *   2. The UI never stays silent. Every outcome -- success, HTTP error, network
 *      failure, timeout, non-JSON response -- ends with something visible.
 *   3. The wait is named honestly. AI wording appears only when an LLM call
 *      really happens (see labelFor).
 */
(function (global) {
    'use strict';

    // Server-side budgets are 5s (quiz grading) and 60s (artifact checklist).
    // The client windows sit above those so a slow-but-alive request is not cut
    // off, while a truly hung one still resolves into a message.
    var DEFAULT_TIMEOUT_MS = 15000;

    var WAITING_LABELS = {
        llm: '🤖 KI prüft deine Antwort …',
        local: 'Prüfe deine Antwort …',
        upload: 'Datei wird geprüft …',
        generic: 'Einen Moment …'
    };

    /* Which wait message a question type earns.
     *
     * short_answer  -> always graded by the LLM.
     * fill_blank    -> exact match is tried server-side first and usually wins, so
     *                  promising "KI" here would be wrong most of the time.
     * multiple_choice -> compared locally, no LLM involved, ever.
     * ordering/matching -> graded deterministically in quiz_grading.py, same as MC.
     *
     * llmEnabled reflects config.LLM_ENABLED (and, for artifact checks, the
     * per-class klasse.llm_artifact_feedback_enabled gate): with no LLM configured
     * nothing may claim an AI is looking at the answer.
     */
    function labelFor(questionType, llmEnabled) {
        if (llmEnabled && questionType === 'short_answer') return WAITING_LABELS.llm;
        if (questionType === 'fill_blank' || questionType === 'multiple_choice' ||
            questionType === 'ordering' || questionType === 'matching') return WAITING_LABELS.local;
        return llmEnabled ? WAITING_LABELS.llm : WAITING_LABELS.local;
    }

    function setBusy(button, waitingLabel) {
        if (!button) return function () {};
        var originalHTML = button.innerHTML;
        var originalDisabled = button.disabled;
        button.disabled = true;
        button.dataset.busy = '1';
        button.classList.add('is-busy');
        button.innerHTML = '<span class="llm-spinner" aria-hidden="true"></span>' +
                           '<span class="llm-busy-label">' + waitingLabel + '</span>';
        button.setAttribute('aria-busy', 'true');

        // Restoring is the caller's only obligation -- it must run on every exit
        // path, which is why callers get it back as a function instead of having
        // to remember a matching "clearBusy" call.
        return function restore() {
            button.disabled = originalDisabled;
            delete button.dataset.busy;
            button.classList.remove('is-busy');
            button.innerHTML = originalHTML;
            button.removeAttribute('aria-busy');
        };
    }

    function isBusy(button) {
        return !!(button && button.dataset && button.dataset.busy);
    }

    /* POST JSON and always resolve to something the caller can render.
     *
     * Never rejects for an expected failure: a non-OK response, a timeout, a
     * dropped connection and an HTML error page (session expired -> login
     * redirect, 500, stale CSRF token) all come back as
     * {ok: false, error: <kind>, message: <German text>} so no caller can
     * accidentally swallow one by forgetting a .catch().
     */
    function postJSON(url, body, options) {
        var meta = document.querySelector('meta[name="csrf-token"]');
        var headers = { 'Content-Type': 'application/json' };
        if (meta) headers['X-CSRFToken'] = meta.content;
        return post(url, { headers: headers, body: JSON.stringify(body) }, options);
    }

    /* Same contract for multipart uploads (artifact gate checks): the CSRF token
     * rides in the form body, as those routes expect. */
    function postForm(url, formData, options) {
        return post(url, { body: formData }, options);
    }

    function post(url, fetchOptions, options) {
        options = options || {};
        var timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;
        var controller = new AbortController();
        var timedOut = false;
        var timer = setTimeout(function () {
            timedOut = true;
            controller.abort();
        }, timeoutMs);

        return fetch(url, {
            method: 'POST',
            headers: fetchOptions.headers,
            body: fetchOptions.body,
            signal: controller.signal
        }).then(function (response) {
            clearTimeout(timer);
            return response.text().then(function (text) {
                var data = null;
                try {
                    data = JSON.parse(text);
                } catch (e) {
                    // An HTML body means we never reached the JSON route at all --
                    // most often an expired session redirecting to the login page.
                    return {
                        ok: false,
                        error: 'not_json',
                        status: response.status,
                        message: response.status === 401 || response.status === 403 || /<html/i.test(text)
                            ? 'Deine Sitzung ist abgelaufen. Bitte lade die Seite neu und melde dich erneut an.'
                            : 'Unerwartete Antwort vom Server. Bitte versuche es noch einmal.'
                    };
                }
                if (!response.ok) {
                    return {
                        ok: false,
                        error: data.error || 'http_' + response.status,
                        status: response.status,
                        message: data.message || data.error ||
                                 'Da ist etwas schiefgelaufen. Bitte versuche es noch einmal.',
                        data: data
                    };
                }
                data.ok = true;
                return data;
            });
        }).catch(function (err) {
            clearTimeout(timer);
            if (timedOut) {
                return {
                    ok: false,
                    error: 'timeout',
                    message: 'Das dauert gerade zu lange. Bitte versuche es noch einmal — ' +
                             'deine Antwort ist nicht verloren.'
                };
            }
            return {
                ok: false,
                error: 'network',
                message: 'Keine Verbindung zum Server. Prüfe die WLAN-Verbindung und ' +
                         'versuche es noch einmal.'
            };
        });
    }

    /* The whole contract in one call: guard, show the wait, run the request,
     * always restore. `run` receives postJSON's result object. */
    function withBusy(button, waitingLabel, requestFn) {
        if (isBusy(button)) return Promise.resolve(null);
        var restore = setBusy(button, waitingLabel);
        return requestFn().then(function (result) {
            restore();
            return result;
        }, function (err) {
            // requestFn should not reject (postJSON never does), but a caller bug
            // must still not leave the button spinning forever.
            restore();
            console.error('LLM button request failed:', err);
            return {
                ok: false,
                error: 'client',
                message: 'Da ist etwas schiefgelaufen. Bitte lade die Seite neu.'
            };
        });
    }

    global.LLMButton = {
        labelFor: labelFor,
        setBusy: setBusy,
        isBusy: isBusy,
        postJSON: postJSON,
        postForm: postForm,
        withBusy: withBusy,
        WAITING_LABELS: WAITING_LABELS,
        DEFAULT_TIMEOUT_MS: DEFAULT_TIMEOUT_MS
    };
})(window);
