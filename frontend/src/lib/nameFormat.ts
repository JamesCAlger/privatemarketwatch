export type DisplayNameKind = 'fund' | 'issuer' | 'manager' | 'generic';

export interface FundNameParts {
  displayName: string;
  ticker: string | null;
}

const ACRONYMS = new Set([
  'AIP',
  'BDC',
  'BMO',
  'CION',
  'CLO',
  'FS',
  'GSO',
  'HPS',
  'KKR',
  'LLC',
  'LP',
  'LLP',
  'NAV',
  'PIMCO',
  'REIT',
  'SLF',
  'TCW',
  'TPG',
  'XAI',
]);

const SMALL_WORDS = new Set(['a', 'an', 'and', 'as', 'at', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to']);

const LEGAL_SUFFIX_PATTERNS: Array<[RegExp, string]> = [
  [/\bL\.?\s*L\.?\s*C\.?(?=\W|$)/gi, 'LLC'],
  [/\bL\.?\s*L\.?\s*P\.?(?=\W|$)/gi, 'LLP'],
  [/\bL\.?\s*P\.?(?=\W|$)/gi, 'LP'],
  [/\bI\.?\s*N\.?\s*C\.?(?=\W|$)/gi, 'Inc'],
  [/\bC\.?\s*O\.?(?=\W|$)/gi, 'Co'],
  [/\bC\.?\s*O\.?\s*R\.?\s*P\.?(?=\W|$)/gi, 'Corp'],
  [/\bL\.?\s*T\.?\s*D\.?(?=\W|$)/gi, 'Ltd'],
  [/\bB\.?\s*D\.?\s*C\.?(?=\W|$)/gi, 'BDC'],
  [/\bR\.?\s*E\.?\s*I\.?\s*T\.?(?=\W|$)/gi, 'REIT'],
];

const ROMAN_NUMERAL_RE = /^(?=[IVXLCDM]+$)M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$/i;
const CIK_SUFFIX_RE = /\s*\(\s*CIK\s+0*\d{1,10}\s*\)\s*$/i;
const TRAILING_TICKER_RE = /\s*\(\s*([A-Z0-9][A-Z0-9.\-]*(?:\s*,\s*[A-Z0-9][A-Z0-9.\-]*)*)\s*\)\s*$/;

function cleanWhitespace(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

function stripCikSuffix(value: string): string {
  let result = value;
  while (CIK_SUFFIX_RE.test(result)) {
    result = result.replace(CIK_SUFFIX_RE, '');
  }
  return result;
}

function stripTerminalSlash(value: string): string {
  return value.replace(/\s+\/\s*$/, '');
}

function canonicalizeLegalSuffixes(value: string): string {
  return LEGAL_SUFFIX_PATTERNS.reduce((result, [pattern, replacement]) => {
    return result.replace(pattern, replacement);
  }, value);
}

function isAllCapsName(value: string): boolean {
  const letters = value.replace(/[^A-Za-z]/g, '');
  return letters.length > 0 && letters === letters.toUpperCase();
}

function titleCaseToken(token: string, index: number, total: number): string {
  const stripped = token.replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9]+$/g, '');
  const upper = stripped.toUpperCase();
  const lower = stripped.toLowerCase();

  if (!stripped) return token;
  if (ACRONYMS.has(upper) || ROMAN_NUMERAL_RE.test(upper)) {
    return token.replace(stripped, upper);
  }
  if (index > 0 && index < total - 1 && SMALL_WORDS.has(lower)) {
    return token.replace(stripped, lower);
  }

  const titled = lower.replace(/(^|[-'])([a-z])/g, (_, prefix: string, letter: string) => {
    return `${prefix}${letter.toUpperCase()}`;
  });
  return token.replace(stripped, titled);
}

function titleCaseAllCaps(value: string): string {
  const tokens = value.split(/(\s+)/);
  const wordIndexes = tokens
    .map((token, i) => ({ token, i }))
    .filter(({ token }) => /\S/.test(token))
    .map(({ i }) => i);

  return tokens
    .map((token, i) => {
      if (!/\S/.test(token)) return token;
      const wordIndex = wordIndexes.indexOf(i);
      return titleCaseToken(token, wordIndex, wordIndexes.length);
    })
    .join('');
}

function normalizeCoreName(rawName: string, kind: DisplayNameKind): string {
  let name = cleanWhitespace(rawName);
  name = stripCikSuffix(name);
  if (kind === 'issuer' || kind === 'generic') {
    name = stripTerminalSlash(name);
  }
  const shouldTitleCase = isAllCapsName(name);
  name = canonicalizeLegalSuffixes(name);
  if (shouldTitleCase) {
    name = titleCaseAllCaps(name);
  }
  name = canonicalizeLegalSuffixes(name);
  return cleanWhitespace(name);
}

function cleanTicker(value: string | null | undefined): string | null {
  const ticker = cleanWhitespace(String(value ?? ''));
  return ticker || null;
}

export function getFundNameParts(rawName: string | null | undefined, explicitTicker?: string | null): FundNameParts {
  let name = cleanWhitespace(String(rawName ?? ''));
  name = stripCikSuffix(name);

  let parsedTicker: string | null = null;
  const tickerMatch = name.match(TRAILING_TICKER_RE);
  if (tickerMatch) {
    parsedTicker = tickerMatch[1].replace(/\s*,\s*/g, ', ');
    name = name.replace(TRAILING_TICKER_RE, '');
  }

  return {
    displayName: normalizeCoreName(name, 'fund'),
    ticker: cleanTicker(explicitTicker) ?? parsedTicker,
  };
}

export function formatDisplayName(
  rawName: string | null | undefined,
  { kind }: { kind: DisplayNameKind },
): string {
  if (kind === 'fund') {
    return getFundNameParts(rawName).displayName;
  }
  return normalizeCoreName(String(rawName ?? ''), kind);
}
