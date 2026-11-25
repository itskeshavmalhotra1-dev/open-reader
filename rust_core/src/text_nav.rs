use pyo3::prelude::*;

/// Represents a sentence boundary in plain text using Python-safe char offsets.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct SentenceSpan {
    pub start: usize,
    pub end: usize,
    pub text: String,
}

/// Represents a case-insensitive search match using Python-safe char offsets.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct SearchHit {
    pub start: usize,
    pub end: usize,
    pub line_number: usize,
    pub snippet: String,
}

/// Split plain text into sentence spans using Python-compatible character indices.
#[pyfunction]
pub fn split_sentences(text: &str) -> Vec<SentenceSpan> {
    let chars: Vec<char> = text.chars().collect();
    let n = chars.len();
    let mut spans = Vec::new();
    let mut start = 0usize;

    let mut i = 0usize;
    while i < n {
        let ch = chars[i];
        let is_sentence_end = matches!(ch, '.' | '!' | '?' | '\u{0964}' | '\u{06D4}');
        let is_newline = ch == '\n';

        if is_sentence_end {
            let mut end = i + 1;
            while end < n && matches!(chars[end], '"' | '\'' | ')' | ']' | '\u{201D}' | '\u{2019}') {
                end += 1;
            }
            if end == n || chars[end].is_whitespace() {
                let slice: String = chars[start..end].iter().collect();
                let trimmed = slice.trim();
                if !trimmed.is_empty() {
                    let lead = slice.chars().take_while(|c| c.is_whitespace()).count();
                    let trail = slice.chars().rev().take_while(|c| c.is_whitespace()).count();
                    spans.push(SentenceSpan {
                        start: start + lead,
                        end: end - trail,
                        text: trimmed.to_string(),
                    });
                }
                start = end;
                i = end;
                continue;
            }
        } else if is_newline {
            let slice: String = chars[start..i].iter().collect();
            let trimmed = slice.trim();
            if !trimmed.is_empty() {
                let lead = slice.chars().take_while(|c| c.is_whitespace()).count();
                let trail = slice.chars().rev().take_while(|c| c.is_whitespace()).count();
                spans.push(SentenceSpan {
                    start: start + lead,
                    end: i - trail,
                    text: trimmed.to_string(),
                });
            }
            start = i + 1;
        }
        i += 1;
    }

    if start < n {
        let slice: String = chars[start..n].iter().collect();
        let trimmed = slice.trim();
        if !trimmed.is_empty() {
            let lead = slice.chars().take_while(|c| c.is_whitespace()).count();
            let trail = slice.chars().rev().take_while(|c| c.is_whitespace()).count();
            spans.push(SentenceSpan {
                start: start + lead,
                end: n - trail,
                text: trimmed.to_string(),
            });
        }
    }

    spans
}

/// Return start character offsets of each non-empty paragraph in plain text.
#[pyfunction]
pub fn paragraph_offsets(text: &str) -> Vec<usize> {
    let mut offsets = Vec::new();
    let mut char_pos = 0usize;
    let mut in_blank = true;

    for line in text.split('\n') {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            in_blank = true;
        } else if in_blank {
            let leading_ws = line.chars().take_while(|c| c.is_whitespace()).count();
            offsets.push(char_pos + leading_ws);
            in_blank = false;
        }
        char_pos += line.chars().count() + 1;
    }

    offsets
}

/// Fast case-insensitive full-text search returning Python char offsets and line snippets.
#[pyfunction]
#[pyo3(signature = (text, query, max_hits=None))]
pub fn search_text(text: &str, query: &str, max_hits: Option<usize>) -> Vec<SearchHit> {
    let needle = query.trim().to_lowercase();
    if needle.is_empty() {
        return Vec::new();
    }
    let limit = max_hits.unwrap_or(200);
    let mut hits = Vec::new();
    let mut char_offset = 0usize;

    for (line_idx, line) in text.split('\n').enumerate() {
        let line_lower = line.to_lowercase();
        let mut search_byte = 0usize;
        while let Some(found_byte) = line_lower[search_byte..].find(&needle) {
            let abs_byte = search_byte + found_byte;
            let match_char_in_line = line_lower[..abs_byte].chars().count();
            let match_char_len = needle.chars().count();
            let start = char_offset + match_char_in_line;
            let end = start + match_char_len;
            hits.push(SearchHit {
                start,
                end,
                line_number: line_idx + 1,
                snippet: line.trim().to_string(),
            });
            if hits.len() >= limit {
                return hits;
            }
            search_byte = abs_byte + needle.len().max(1);
        }
        char_offset += line.chars().count() + 1;
    }

    hits
}
