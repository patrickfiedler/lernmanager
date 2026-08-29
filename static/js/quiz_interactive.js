/* Renderer and answer reader for the `ordering` and `matching` question types.
 *
 * One module, four callers: the server-rendered quiz form (quiz.html) and the
 * three JS-driven pages (warmup, practice, checkpoint). Those four already
 * carry near-identical copies of the multiple-choice renderer; adding a fifth
 * and sixth copy of something this fiddly was not worth it.
 *
 * Pointer, not HTML5 drag-and-drop: dragstart/drop never fire on touch, and the
 * cohort these types were requested for works exclusively on iPads. Pointer
 * events give mouse, pen and touch from one code path.
 *
 * Every drag has two equivalents, so nothing here is reachable only by dragging:
 *   - tap: a pointerdown that never moves selects, and the next tap places.
 *   - keyboard: ordering rows carry real up/down buttons; matching chips and
 *     slots are role="button" and answer Enter/Space, so the gesture is
 *     Tab-to-chip, Enter, Tab-to-row, Enter.
 * Chemie asked for select boxes precisely because drag is unreliable on touch;
 * this is the same guarantee without a second UI to keep in sync.
 *
 * Answers are read back as *text*, never as an index -- an index-based protocol
 * would need the authored order on the client, which is the answer key.
 */
(function () {
    'use strict';

    var DRAG_THRESHOLD = 6;   // px of movement before a tap becomes a drag
    /* A finished drag is followed by a synthetic click on whatever is under the
     * pointer. Left alone, that click reaches the slot the chip was just dropped
     * on and undoes the drop.
     *
     * It swallows exactly that one click, at document capture depth, and gives up
     * after a frame or two if none arrives. The first attempt was a 300 ms
     * "ignore clicks after a drag" window on the drop target, which also ate the
     * student's next genuine tap whenever it came quickly -- a tap-to-place right
     * after a drag silently did nothing. */
    function swallowNextClick() {
        var done;
        function onClick(e) { e.stopPropagation(); done(); }
        var timer = setTimeout(function () { done(); }, 50);
        done = function () {
            clearTimeout(timer);
            document.removeEventListener('click', onClick, true);
        };
        document.addEventListener('click', onClick, true);
    }

    function supports(type) {
        return type === 'ordering' || type === 'matching';
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    /* ---------- ordering ---------- */

    function renderOrdering(container, question, onChange) {
        var list = el('div', 'qi-list qi-ordering');
        list.setAttribute('role', 'list');
        (question.items || []).forEach(function (text, i) {
            list.appendChild(orderingRow(text, i, list, onChange));
        });
        container.appendChild(list);
        makeListSortable(list, onChange);
        renumber(list);

        var hint = el('p', 'text-muted qi-hint',
            'Zieh die Zeilen in die richtige Reihenfolge — oder nutze die Pfeiltasten ▲▼ '
            + 'an jeder Zeile (mit Tab erreichbar).');
        container.appendChild(hint);
    }

    function orderingRow(text, index, list, onChange) {
        var row = el('div', 'qi-item');
        row.setAttribute('role', 'listitem');
        row.dataset.text = text;

        var handle = el('span', 'qi-handle', '⠿');
        handle.setAttribute('aria-hidden', 'true');
        row.appendChild(handle);
        row.appendChild(el('span', 'qi-pos'));
        row.appendChild(el('span', 'qi-text', text));

        var controls = el('span', 'qi-controls');
        controls.appendChild(moveButton('▲', 'Nach oben', -1, row, list, onChange));
        controls.appendChild(moveButton('▼', 'Nach unten', 1, row, list, onChange));
        row.appendChild(controls);

        return row;
    }

    function moveButton(glyph, label, delta, row, list, onChange) {
        var btn = el('button', 'qi-move', glyph);
        btn.type = 'button';
        btn.setAttribute('aria-label', label);
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            if (list.dataset.locked) return;
            var sibling = delta < 0 ? row.previousElementSibling : row.nextElementSibling;
            if (!sibling) return;
            if (delta < 0) list.insertBefore(row, sibling);
            else list.insertBefore(sibling, row);
            renumber(list);
            flash(row);
            // insertBefore re-inserts the row, and re-inserting an element blurs
            // whatever inside it had focus -- so without this the second Enter
            // went nowhere and the item moved exactly one step per Tab. When the
            // item lands at an end its own arrow is now disabled, so focus goes
            // to the other one rather than to the top of the page.
            var arrows = row.querySelectorAll('.qi-move');
            var keep = btn.disabled ? arrows[delta < 0 ? 1 : 0] : btn;
            if (keep && !keep.disabled) keep.focus();
            if (onChange) onChange();
        });
        return btn;
    }

    function renumber(list) {
        Array.prototype.forEach.call(list.children, function (row, i) {
            var pos = row.querySelector('.qi-pos');
            if (pos) pos.textContent = (i + 1) + '.';
            var buttons = row.querySelectorAll('.qi-move');
            if (buttons.length === 2) {
                buttons[0].disabled = (i === 0);
                buttons[1].disabled = (i === list.children.length - 1);
            }
        });
    }

    /* Reorder-by-drag. The dragged row is moved between its siblings as the
     * pointer crosses their midpoints, so the list the student sees during the
     * drag is already the list they will get.
     *
     * The pointer is captured on the LIST, not on the row. insertBefore()
     * re-inserts the dragged node, and re-inserting an element releases its
     * pointer capture -- capturing on the row meant the browser stopped routing
     * pointermove to it after the first reorder and the drag died three pixels
     * in. The list never moves, so its capture survives the whole gesture. */
    function makeListSortable(list, onChange) {
        var row = null;
        onPointerDrag(list, {
            locked: function () { return !!list.dataset.locked; },
            canStart: function (e) {
                if (e.target.closest('.qi-move')) return false;   // arrows are buttons
                row = e.target.closest('.qi-item');
                return !!row;
            },
            start: function () { row.classList.add('qi-dragging'); },
            move: function (e) {
                var target = rowUnder(list, row, e.clientY);
                if (!target) return;
                var box = target.getBoundingClientRect();
                var after = e.clientY > box.top + box.height / 2;
                list.insertBefore(row, after ? target.nextElementSibling : target);
                renumber(list);
            },
            end: function (dragged) {
                if (row) row.classList.remove('qi-dragging');
                if (dragged && onChange) onChange();
            },
            tap: function () { /* ordering uses the arrows, not tap-to-place */ }
        });
    }

    function rowUnder(list, exclude, clientY) {
        var found = null;
        Array.prototype.forEach.call(list.children, function (candidate) {
            if (candidate === exclude) return;
            var box = candidate.getBoundingClientRect();
            if (clientY >= box.top && clientY <= box.bottom) found = candidate;
        });
        return found;
    }

    /* ---------- matching ---------- */

    function renderMatching(container, question, onChange) {
        var wrap = el('div', 'qi-matching');

        var slots = el('div', 'qi-slots');
        (question.left || []).forEach(function (leftText) {
            slots.appendChild(matchingRow(leftText, wrap, onChange));
        });

        var pool = el('div', 'qi-pool');
        pool.dataset.role = 'pool';
        var poolLabel = el('div', 'qi-pool-label', 'Zum Zuordnen:');
        (question.right || []).forEach(function (rightText) {
            pool.appendChild(chip(rightText, wrap, onChange));
        });

        wrap.appendChild(slots);
        wrap.appendChild(poolLabel);
        wrap.appendChild(pool);
        container.appendChild(wrap);

        makeDropTarget(pool, wrap, onChange);

        var hint = el('p', 'text-muted qi-hint',
            'Zieh die Bausteine auf die passende Zeile — oder wähle erst den Baustein aus, '
            + 'dann die Zeile (mit Tippen oder mit Tab und Enter).');
        container.appendChild(hint);
    }

    function matchingRow(leftText, wrap, onChange) {
        var row = el('div', 'qi-match-row');
        row.appendChild(el('span', 'qi-left', leftText));
        row.appendChild(el('span', 'qi-arrow', '→'));

        var slot = el('div', 'qi-slot');
        slot.dataset.left = leftText;
        slot.dataset.role = 'slot';
        slot.appendChild(el('span', 'qi-slot-empty', 'hierhin ziehen'));
        makeDropTarget(slot, wrap, onChange);
        describeSlot(slot);
        row.appendChild(slot);
        return row;
    }

    /* Without this a keyboard or screen-reader user tabs onto an anonymous
     * "button" and has no way to tell which row it is or what is in it. */
    function describeSlot(slot) {
        var occupant = slot.querySelector('.qi-chip');
        slot.setAttribute('aria-label', 'Zeile „' + slot.dataset.left + '": '
            + (occupant ? 'zugeordnet: ' + occupant.dataset.text : 'noch leer'));
    }

    function chip(text, wrap, onChange) {
        var node = el('div', 'qi-chip');
        node.dataset.text = text;
        node.appendChild(el('span', 'qi-text', text));
        node.setAttribute('aria-label', 'Baustein: ' + text);

        onPointerDrag(node, {
            locked: function () { return !!wrap.dataset.locked; },
            start: function () {
                node.classList.add('qi-dragging');
                clearSelection(wrap);
            },
            move: function (e) { highlightDropTarget(wrap, dropTargetAt(wrap, e)); },
            end: function (dragged, e) {
                node.classList.remove('qi-dragging');
                highlightDropTarget(wrap, null);
                if (!dragged) return;
                var target = dropTargetAt(wrap, e);
                if (target) placeChip(node, target, wrap, onChange);
            }
        });

        // Tap-to-place: tap the chip, then tap its row. Same result as the drag,
        // and the route that survives a shaky finger on a tablet. It hangs off
        // `click` rather than the pointer gesture so that mouse, touch, keyboard
        // and a programmatic activation all arrive the same way -- a drag's own
        // trailing click is swallowed before it gets here (swallowNextClick).
        // A chip already sitting in a row arms identically, so moving it out is
        // tap-chip then tap-the-pool: placing it, in reverse.
        activatable(node, function () {
            if (wrap.dataset.locked) return;
            if (node.classList.contains('qi-selected')) {
                node.classList.remove('qi-selected');
                return;
            }
            clearSelection(wrap);
            node.classList.add('qi-selected');
            node.setAttribute('aria-pressed', 'true');
        });
        return node;
    }

    /* Make a plain div behave like a button for anyone not using a pointer.
     * The pieces cannot be real <button>s: a chip is moved *into* a slot, and
     * nesting a button inside a button is invalid and breaks activation. */
    function activatable(node, onActivate) {
        node.setAttribute('role', 'button');
        node.setAttribute('tabindex', '0');
        node.addEventListener('click', onActivate);
        node.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            e.preventDefault();
            onActivate(e);
        });
    }

    function makeDropTarget(target, wrap, onChange) {
        activatable(target, function (e) {
            if (wrap.dataset.locked) return;
            // A click that started on a chip belongs to that chip's own handler.
            // Without this the pool -- itself a drop target, and the chip's own
            // parent -- caught the arming tap on the way up and immediately
            // "placed" the chip back into the pool, disarming it.
            if (e && e.target && e.target.closest('.qi-chip')) return;
            var selected = wrap.querySelector('.qi-chip.qi-selected');
            if (!selected) return;
            placeChip(selected, target, wrap, onChange);
            selected.classList.remove('qi-selected');
            // Keyboard users would otherwise be dropped back to the top of the
            // tab order after every placement.
            if (typeof target.focus === 'function') target.focus();
        });
    }

    function placeChip(node, target, wrap, onChange) {
        // A slot holds exactly one chip; whatever was there goes back to the pool.
        if (target.dataset.role === 'slot') {
            var occupant = target.querySelector('.qi-chip');
            if (occupant && occupant !== node) {
                wrap.querySelector('[data-role="pool"]').appendChild(occupant);
            }
            target.classList.add('qi-filled');
        }
        var previous = node.parentElement;
        target.appendChild(node);
        if (previous && previous.dataset.role === 'slot' && !previous.querySelector('.qi-chip')) {
            previous.classList.remove('qi-filled');
        }
        node.removeAttribute('aria-pressed');
        [previous, target].forEach(function (n) {
            if (n && n.dataset.role === 'slot') describeSlot(n);
        });
        flash(node);
        if (onChange) onChange();
    }

    function dropTargetAt(wrap, e) {
        var found = null;
        wrap.querySelectorAll('[data-role="slot"], [data-role="pool"]').forEach(function (candidate) {
            var box = candidate.getBoundingClientRect();
            if (e.clientX >= box.left && e.clientX <= box.right &&
                e.clientY >= box.top && e.clientY <= box.bottom) found = candidate;
        });
        return found;
    }

    function highlightDropTarget(wrap, target) {
        wrap.querySelectorAll('.qi-over').forEach(function (n) { n.classList.remove('qi-over'); });
        if (target) target.classList.add('qi-over');
    }

    function clearSelection(wrap) {
        wrap.querySelectorAll('.qi-selected').forEach(function (n) {
            n.classList.remove('qi-selected');
            n.removeAttribute('aria-pressed');
        });
    }

    /* ---------- shared pointer handling ---------- */

    /* One gesture recogniser for both types. Below DRAG_THRESHOLD the gesture is
     * a tap and the page keeps scrolling normally; past it the element is
     * captured and `touch-action: none` (set in CSS) stops the browser from
     * turning the drag into a scroll. */
    function onPointerDrag(node, handlers) {
        var startX = 0, startY = 0, dragging = false, active = false;

        node.addEventListener('pointerdown', function (e) {
            if (e.button !== undefined && e.button !== 0) return;
            if (handlers.locked && handlers.locked()) return;
            // canStart also decides WHICH element the gesture is about when the
            // listener sits on a container rather than on the draggable itself.
            if (handlers.canStart && !handlers.canStart(e)) return;
            active = true;
            dragging = false;
            startX = e.clientX;
            startY = e.clientY;
        });

        node.addEventListener('pointermove', function (e) {
            if (!active) return;
            if (!dragging) {
                if (Math.abs(e.clientX - startX) < DRAG_THRESHOLD &&
                    Math.abs(e.clientY - startY) < DRAG_THRESHOLD) return;
                dragging = true;
                try { node.setPointerCapture(e.pointerId); } catch (err) { /* stale pointer */ }
                if (handlers.start) handlers.start(e);
            }
            e.preventDefault();
            if (handlers.move) handlers.move(e);
        });

        function finish(e) {
            if (!active) return;
            active = false;
            try { node.releasePointerCapture(e.pointerId); } catch (err) { /* already gone */ }
            if (dragging) swallowNextClick();
            if (handlers.end) handlers.end(dragging, e);
            // A drag that ends on the element must not also fire the tap
            // handler, or a chip dropped back where it started would arm itself.
            if (!dragging && handlers.tap) handlers.tap(e);
            dragging = false;
        }

        node.addEventListener('pointerup', finish);
        node.addEventListener('pointercancel', finish);
    }

    function flash(node) {
        node.classList.remove('qi-flash');
        void node.offsetWidth;            // restart the animation
        node.classList.add('qi-flash');
    }

    /* ---------- public API ---------- */

    function render(container, question, onChange) {
        container.innerHTML = '';
        delete container.dataset.locked;
        container.classList.remove('qi-locked');
        if (question.type === 'ordering') renderOrdering(container, question, onChange);
        else if (question.type === 'matching') renderMatching(container, question, onChange);
    }

    function getAnswer(container, question) {
        if (question.type === 'ordering') {
            return Array.prototype.map.call(
                container.querySelectorAll('.qi-ordering .qi-item'),
                function (row) { return row.dataset.text; });
        }
        var answer = {};
        container.querySelectorAll('[data-role="slot"]').forEach(function (slot) {
            var occupant = slot.querySelector('.qi-chip');
            if (occupant) answer[slot.dataset.left] = occupant.dataset.text;
        });
        return answer;
    }

    /* "Empty" means untouched. An ordering question always carries an order, so
     * there is nothing to withhold -- the student has seen it and can submit it.
     * A matching question with no chip placed has genuinely not been answered,
     * and in a checkpoint an empty submit would burn a scored attempt. */
    function isEmpty(container, question) {
        if (question.type === 'ordering') return false;
        return Object.keys(getAnswer(container, question)).length === 0;
    }

    function lock(container) {
        container.dataset.locked = '1';
        var wrap = container.querySelector('.qi-matching') || container.querySelector('.qi-list');
        if (wrap) wrap.dataset.locked = '1';
        container.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
        container.querySelectorAll('[role="button"]').forEach(function (n) {
            n.setAttribute('tabindex', '-1');
        });
        container.classList.add('qi-locked');
    }

    window.QuizInteractive = {
        supports: supports,
        render: render,
        getAnswer: getAnswer,
        isEmpty: isEmpty,
        lock: lock
    };
})();
