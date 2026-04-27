// Variable interpolation for scenario content.
//
// Mirror of backend/app/services/scenario_interpolation.py — keep the rules
// in lockstep so authors learn one syntax:
//
//   {var_name}     → answers[var_name].value (or answer if a string)
//   {{ }}          → literal { } braces
//   \{var}         → literal {var}; the leading backslash is consumed
//   missing var    → token left literal so authors can spot typos
//
// Replacement is single-pass: substituted values are NOT re-interpolated.

const VAR_RE = /(\\?)\{([a-z_][a-z0-9_]*)\}/g
// Private-use Unicode codepoints — never appear in real prose.
const OPEN_SENTINEL = '__LBR__'
const CLOSE_SENTINEL = '__RBR__'

const coerceValue = (answer) => {
  if (answer == null) return null
  if (typeof answer === 'object') {
    const v = answer.value
    if (v == null) return null
    const s = String(v).trim()
    return s.length > 0 ? s : null
  }
  const s = String(answer).trim()
  return s.length > 0 ? s : null
}

export function interpolate(template, answers) {
  if (!template) return ''
  const ans = answers || {}
  const work = template
    .split('{{').join(OPEN_SENTINEL)
    .split('}}').join(CLOSE_SENTINEL)
  const replaced = work.replace(VAR_RE, (match, backslash, key) => {
    if (backslash) {
      // \{var} → keep {var} literal, drop the backslash
      return match.slice(1)
    }
    const value = coerceValue(ans[key])
    return value == null ? match : value
  })
  return replaced.split(OPEN_SENTINEL).join('{').split(CLOSE_SENTINEL).join('}')
}

export default interpolate
