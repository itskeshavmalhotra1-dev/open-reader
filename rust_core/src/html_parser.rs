use pyo3::prelude::*;
use quick_xml::events::{BytesStart, Event};
use quick_xml::Reader;
use std::collections::HashMap;

/// Represents a heading extracted from HTML/XHTML content with its character offset.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct HeadingOffset {
    pub level: u8,
    pub text: String,
    pub char_offset: usize,
}

/// Represents a print page break marker inside HTML/XHTML content.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct PageBreakOffset {
    pub label: String,
    pub char_offset: usize,
}

/// Complete structured extraction result from HTML/XHTML.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct HtmlExtractResult {
    pub text: String,
    pub headings: Vec<HeadingOffset>,
    pub anchors: HashMap<String, usize>,
    pub page_breaks: Vec<PageBreakOffset>,
}

fn push_normalized_text(out: &mut String, chunk: &str, char_len: &mut usize) {
    let mut prev_space = out.ends_with(char::is_whitespace);
    for ch in chunk.chars() {
        let mapped = if ch == '\u{00A0}' { ' ' } else { ch };
        if mapped.is_whitespace() {
            if !prev_space && !out.is_empty() {
                out.push(' ');
                *char_len += 1;
                prev_space = true;
            }
        } else {
            out.push(mapped);
            *char_len += 1;
            prev_space = false;
        }
    }
}

fn ensure_newline(out: &mut String, char_len: &mut usize, double: bool) {
    while out.ends_with(' ') {
        out.pop();
        *char_len -= 1;
    }
    if out.is_empty() {
        return;
    }
    if !out.ends_with('\n') {
        out.push('\n');
        *char_len += 1;
    }
    if double && !out.ends_with("\n\n") {
        out.push('\n');
        *char_len += 1;
    }
}

fn heading_level(tag_lower: &str) -> Option<u8> {
    match tag_lower {
        "h1" => Some(1),
        "h2" => Some(2),
        "h3" => Some(3),
        "h4" => Some(4),
        "h5" => Some(5),
        "h6" => Some(6),
        _ => None,
    }
}

fn is_block_tag(tag_lower: &str) -> bool {
    matches!(
        tag_lower,
        "p" | "div" | "section" | "article" | "li" | "tr" | "blockquote" | "pre"
            | "h1" | "h2" | "h3" | "h4" | "h5" | "h6"
    )
}

fn decode_html_entity(entity: &str) -> Option<char> {
    if let Some(hex) = entity.strip_prefix("#x").or_else(|| entity.strip_prefix("#X")) {
        return u32::from_str_radix(hex, 16).ok().and_then(char::from_u32);
    }
    if let Some(dec) = entity.strip_prefix('#') {
        return dec.parse::<u32>().ok().and_then(char::from_u32);
    }
    match entity {
        "amp" => Some('&'),
        "lt" => Some('<'),
        "gt" => Some('>'),
        "quot" => Some('"'),
        "apos" => Some('\''),
        "nbsp" => Some(' '),
        "mdash" => Some('\u{2014}'),
        "ndash" => Some('\u{2013}'),
        "hellip" => Some('\u{2026}'),
        "lsquo" => Some('\u{2018}'),
        "rsquo" => Some('\u{2019}'),
        "ldquo" => Some('\u{201C}'),
        "rdquo" => Some('\u{201D}'),
        "copy" => Some('\u{00A9}'),
        "reg" => Some('\u{00AE}'),
        "trade" => Some('\u{2122}'),
        _ => None,
    }
}

fn unescape_html_text(raw: &str) -> String {
    if !raw.contains('&') {
        return raw.to_string();
    }
    let mut out = String::with_capacity(raw.len());
    let mut rest = raw;
    while let Some(amp_idx) = rest.find('&') {
        out.push_str(&rest[..amp_idx]);
        let after_amp = &rest[amp_idx + 1..];
        if let Some(semi_idx) = after_amp.find(';') {
            let entity = &after_amp[..semi_idx];
            if !entity.is_empty() && entity.len() <= 16 {
                if let Some(ch) = decode_html_entity(entity) {
                    out.push(ch);
                    rest = &after_amp[semi_idx + 1..];
                    continue;
                }
            }
        }
        out.push('&');
        rest = after_amp;
    }
    out.push_str(rest);
    out
}

fn inspect_element_attrs(
    e: &BytesStart<'_>,
    char_len: usize,
    anchors: &mut HashMap<String, usize>,
) -> Option<(String, usize)> {
    let mut elem_id: Option<String> = None;
    let mut is_pagebreak = false;
    let mut pb_label: Option<String> = None;

    for attr in e.attributes().flatten() {
        let key = String::from_utf8_lossy(attr.key.as_ref()).to_lowercase();
        let val = attr.unescape_value().map(|v| v.into_owned()).unwrap_or_default();
        if key == "id" && !val.trim().is_empty() {
            elem_id = Some(val.trim().to_string());
        } else if (key == "epub:type" || key == "type" || key == "role")
            && (val.contains("pagebreak") || val.contains("doc-pagebreak"))
        {
            is_pagebreak = true;
        } else if (key == "title" || key == "aria-label") && !val.trim().is_empty() {
            pb_label = Some(val.trim().to_string());
        }
    }

    if let Some(id) = elem_id {
        anchors.entry(id).or_insert(char_len);
    }
    if is_pagebreak {
        Some((pb_label.unwrap_or_default(), char_len))
    } else {
        None
    }
}

/// Extract clean text, headings, id anchors, and pagebreak markers from HTML/XHTML.
#[pyfunction]
pub fn extract_html_document(html: &str) -> PyResult<HtmlExtractResult> {
    let mut reader = Reader::from_str(html);
    reader.config_mut().trim_text(false);
    reader.config_mut().check_end_names = false;

    let mut out = String::with_capacity(html.len() / 2);
    let mut char_len: usize = 0;
    let mut headings: Vec<HeadingOffset> = Vec::new();
    let mut anchors: HashMap<String, usize> = HashMap::new();
    let mut page_breaks: Vec<PageBreakOffset> = Vec::new();

    let mut skip_depth: usize = 0;
    let mut active_heading: Option<(u8, usize, String)> = None;
    let mut active_pagebreak: Option<(String, String, usize, String)> = None;
    let mut buf = Vec::new();

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_lowercase();
                if matches!(name.as_str(), "script" | "style" | "head") {
                    skip_depth += 1;
                } else if skip_depth == 0 {
                    if is_block_tag(&name) {
                        ensure_newline(&mut out, &mut char_len, true);
                    } else if name == "br" {
                        ensure_newline(&mut out, &mut char_len, false);
                    }
                    if let Some((pb_lbl, pb_offset)) =
                        inspect_element_attrs(&e, char_len, &mut anchors)
                    {
                        active_pagebreak = Some((name.clone(), pb_lbl, pb_offset, String::new()));
                    }
                    if let Some(lvl) = heading_level(&name) {
                        active_heading = Some((lvl, char_len, String::new()));
                    }
                }
            }
            Ok(Event::Empty(e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_lowercase();
                if skip_depth == 0 {
                    if name == "br" {
                        ensure_newline(&mut out, &mut char_len, false);
                    }
                    if let Some((pb_lbl, pb_offset)) =
                        inspect_element_attrs(&e, char_len, &mut anchors)
                    {
                        if !pb_lbl.is_empty() {
                            page_breaks.push(PageBreakOffset {
                                label: pb_lbl,
                                char_offset: pb_offset,
                            });
                        }
                    }
                }
            }
            Ok(Event::End(e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_lowercase();
                if matches!(name.as_str(), "script" | "style" | "head") {
                    skip_depth = skip_depth.saturating_sub(1);
                } else if skip_depth == 0 {
                    if let Some((pb_tag, pb_lbl, pb_offset, pb_inner)) = active_pagebreak.take() {
                        if pb_tag == name {
                            let label = if !pb_lbl.is_empty() {
                                pb_lbl
                            } else {
                                pb_inner.split_whitespace().collect::<Vec<_>>().join(" ")
                            };
                            if !label.is_empty() {
                                page_breaks.push(PageBreakOffset {
                                    label,
                                    char_offset: pb_offset,
                                });
                            }
                        } else {
                            active_pagebreak = Some((pb_tag, pb_lbl, pb_offset, pb_inner));
                        }
                    }
                    if let Some(lvl) = heading_level(&name) {
                        if let Some((active_lvl, offset, title)) = active_heading.take() {
                            if active_lvl == lvl {
                                let clean_title =
                                    title.split_whitespace().collect::<Vec<_>>().join(" ");
                                if !clean_title.is_empty() {
                                    headings.push(HeadingOffset {
                                        level: active_lvl,
                                        text: clean_title,
                                        char_offset: offset,
                                    });
                                }
                            }
                        }
                    }
                    if is_block_tag(&name) {
                        ensure_newline(&mut out, &mut char_len, true);
                    }
                }
            }
            Ok(Event::Text(e)) => {
                if skip_depth == 0 {
                    let raw = String::from_utf8_lossy(e.as_ref());
                    let text = unescape_html_text(&raw);
                    push_normalized_text(&mut out, &text, &mut char_len);
                    if let Some((_, _, ref mut h_text)) = active_heading {
                        h_text.push_str(&text);
                    }
                    if let Some((_, _, _, ref mut pb_text)) = active_pagebreak {
                        pb_text.push_str(&text);
                    }
                }
            }
            Ok(Event::CData(e)) => {
                if skip_depth == 0 {
                    let text = String::from_utf8_lossy(e.as_ref());
                    push_normalized_text(&mut out, &text, &mut char_len);
                    if let Some((_, _, ref mut h_text)) = active_heading {
                        h_text.push_str(&text);
                    }
                }
            }
            Ok(Event::Eof) => break,
            Err(_) => {}
            _ => {}
        }
        buf.clear();
    }

    Ok(HtmlExtractResult {
        text: out.trim_end().to_string(),
        headings,
        anchors,
        page_breaks,
    })
}

/// Backward-compatible wrapper returning (text, headings).
#[pyfunction]
pub fn extract_html_text_and_headings(html: &str) -> PyResult<(String, Vec<HeadingOffset>)> {
    let res = extract_html_document(html)?;
    Ok((res.text, res.headings))
}
