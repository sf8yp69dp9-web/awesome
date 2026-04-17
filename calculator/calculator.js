'use strict';

const display = document.getElementById('result');
const expressionEl = document.getElementById('expression');

const state = {
  current: '0',
  previous: null,
  operator: null,
  waitingForOperand: false,
  expression: '',
};

function updateDisplay() {
  display.textContent = formatNumber(state.current);
  display.classList.toggle('shrink', state.current.length > 9);
  expressionEl.textContent = state.expression;
}

function formatNumber(value) {
  if (value === 'Fehler') return 'Fehler';
  const num = parseFloat(value);
  if (isNaN(num)) return value;
  if (Math.abs(num) >= 1e15 || (Math.abs(num) < 1e-6 && num !== 0)) {
    return num.toExponential(6).replace(/\.?0+e/, 'e');
  }
  const parts = value.split('.');
  const intPart = parseInt(parts[0], 10).toLocaleString('de-DE');
  return parts.length > 1 ? `${intPart},${parts[1]}` : intPart;
}

function inputDigit(digit) {
  if (state.waitingForOperand) {
    state.current = digit;
    state.waitingForOperand = false;
  } else {
    state.current = state.current === '0' ? digit : state.current + digit;
  }
}

function inputDecimal() {
  if (state.waitingForOperand) {
    state.current = '0.';
    state.waitingForOperand = false;
    return;
  }
  if (!state.current.includes('.')) {
    state.current += '.';
  }
}

function calculate(a, b, op) {
  const x = parseFloat(a);
  const y = parseFloat(b);
  switch (op) {
    case '+': return x + y;
    case '-': return x - y;
    case '*': return x * y;
    case '/': return y === 0 ? 'Fehler' : x / y;
  }
}

function handleOperator(op) {
  if (state.operator && !state.waitingForOperand) {
    const result = calculate(state.previous, state.current, state.operator);
    state.current = result === 'Fehler' ? 'Fehler' : String(result);
    state.expression = `${formatNumber(state.current)} ${opSymbol(op)}`;
    state.previous = state.current;
  } else {
    state.previous = state.current;
    state.expression = `${formatNumber(state.current)} ${opSymbol(op)}`;
  }
  state.operator = op;
  state.waitingForOperand = true;
  highlightOperator(op);
}

function handleEquals() {
  if (!state.operator || state.waitingForOperand) return;
  const result = calculate(state.previous, state.current, state.operator);
  state.expression = `${formatNumber(state.previous)} ${opSymbol(state.operator)} ${formatNumber(state.current)} =`;
  state.current = result === 'Fehler' ? 'Fehler' : String(parseFloat(result.toPrecision(15)));
  state.operator = null;
  state.previous = null;
  state.waitingForOperand = true;
  highlightOperator(null);
}

function clearAll() {
  state.current = '0';
  state.previous = null;
  state.operator = null;
  state.waitingForOperand = false;
  state.expression = '';
  highlightOperator(null);
}

function toggleSign() {
  if (state.current === '0' || state.current === 'Fehler') return;
  state.current = state.current.startsWith('-')
    ? state.current.slice(1)
    : '-' + state.current;
}

function applyPercent() {
  const num = parseFloat(state.current);
  if (isNaN(num)) return;
  if (state.operator && state.previous !== null) {
    state.current = String((parseFloat(state.previous) * num) / 100);
  } else {
    state.current = String(num / 100);
  }
}

function opSymbol(op) {
  return { '+': '+', '-': '−', '*': '×', '/': '÷' }[op] || op;
}

function highlightOperator(op) {
  document.querySelectorAll('.btn-operator').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.value === op);
  });
}

document.querySelector('.buttons').addEventListener('click', e => {
  const btn = e.target.closest('.btn');
  if (!btn) return;

  const { value, action } = btn.dataset;

  if (action) {
    switch (action) {
      case 'clear-all': clearAll(); break;
      case 'toggle-sign': toggleSign(); break;
      case 'percent': applyPercent(); break;
      case 'decimal': inputDecimal(); break;
      case 'equals': handleEquals(); break;
    }
  } else if (value) {
    if (['+', '-', '*', '/'].includes(value)) {
      handleOperator(value);
    } else {
      inputDigit(value);
    }
  }

  updateDisplay();
});

document.addEventListener('keydown', e => {
  if (e.key >= '0' && e.key <= '9') inputDigit(e.key);
  else if (e.key === '.') inputDecimal();
  else if (e.key === '+') handleOperator('+');
  else if (e.key === '-') handleOperator('-');
  else if (e.key === '*') handleOperator('*');
  else if (e.key === '/') { e.preventDefault(); handleOperator('/'); }
  else if (e.key === 'Enter' || e.key === '=') handleEquals();
  else if (e.key === 'Escape') clearAll();
  else if (e.key === 'Backspace') {
    if (state.current.length > 1) {
      state.current = state.current.slice(0, -1);
    } else {
      state.current = '0';
    }
  } else return;
  updateDisplay();
});

updateDisplay();
