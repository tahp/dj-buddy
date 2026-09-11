const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');

test('failed job clears previously available save controls', () => {
    const elements = new Map();
    const document = {
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, {
                style: {}, classList: {add() {}},
                removeAttribute(name) { delete this[name]; }
            });
            return elements.get(id);
        }
    };
    // Load the UI functions without page startup or network requests.
    const source = readFileSync('static/js/script.js', 'utf8');
    const context = vm.createContext({document});
    vm.runInContext(source.slice(source.indexOf('function updateJobUI('),
                                source.indexOf('loadHistory();\nrestoreCurrentJob();')), context);
    document.getElementById('completeBox').style.display = 'block';
    document.getElementById('downloadLink').href = '/download/old.mp3';
    context.updateJobUI({title: 'Track', status: 'error', stage: 'error',
        progress: 0, message: 'No MP3 was created.', log: [], file_available: false});
    assert.equal(document.getElementById('completeBox').style.display, 'none');
    assert.equal(document.getElementById('downloadLink').href, undefined);
    assert.equal(document.getElementById('stageText').textContent, 'Error');
    assert.equal(document.getElementById('cancelBtn').style.display, 'none');
});
