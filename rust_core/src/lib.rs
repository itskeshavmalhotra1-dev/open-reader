mod audio_player;
mod html_parser;
mod text_nav;

use pyo3::prelude::*;

use audio_player::{
    float32_to_trimmed_wav, rust_play_audio_bytes, rust_stop_audio, trim_wav_silence,
};
use html_parser::{
    extract_html_document, extract_html_text_and_headings, HeadingOffset, HtmlExtractResult,
    PageBreakOffset,
};
use text_nav::{paragraph_offsets, search_text, split_sentences, SearchHit, SentenceSpan};

#[pymodule]
fn book_reader_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<HeadingOffset>()?;
    m.add_class::<PageBreakOffset>()?;
    m.add_class::<HtmlExtractResult>()?;
    m.add_class::<SentenceSpan>()?;
    m.add_class::<SearchHit>()?;
    m.add_function(wrap_pyfunction!(extract_html_document, m)?)?;
    m.add_function(wrap_pyfunction!(extract_html_text_and_headings, m)?)?;
    m.add_function(wrap_pyfunction!(split_sentences, m)?)?;
    m.add_function(wrap_pyfunction!(paragraph_offsets, m)?)?;
    m.add_function(wrap_pyfunction!(search_text, m)?)?;
    m.add_function(wrap_pyfunction!(rust_play_audio_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(rust_stop_audio, m)?)?;
    m.add_function(wrap_pyfunction!(float32_to_trimmed_wav, m)?)?;
    m.add_function(wrap_pyfunction!(trim_wav_silence, m)?)?;
    Ok(())
}
