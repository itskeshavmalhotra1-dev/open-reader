use pyo3::prelude::*;
use pyo3::types::PyBytes;
use rodio::{Decoder, OutputStream, OutputStreamHandle, Sink};
use std::io::Cursor;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::Duration;

// Dedicated audio thread keeps OutputStream + Sink Send+Sync safe on Windows WASAPI.
enum AudioCmd {
    PlayBytes {
        data: Vec<u8>,
        done_tx: std::sync::mpsc::Sender<Result<(), String>>,
    },
    Stop,
}

static AUDIO_TX: OnceLock<std::sync::mpsc::Sender<AudioCmd>> = OnceLock::new();
static STOP_FLAG: OnceLock<Arc<AtomicBool>> = OnceLock::new();

fn get_stop_flag() -> &'static Arc<AtomicBool> {
    STOP_FLAG.get_or_init(|| Arc::new(AtomicBool::new(false)))
}

fn get_audio_tx() -> &'static std::sync::mpsc::Sender<AudioCmd> {
    AUDIO_TX.get_or_init(|| {
        let (tx, rx) = std::sync::mpsc::channel::<AudioCmd>();
        let stop_flag = get_stop_flag().clone();
        std::thread::spawn(move || {
            let Ok((_stream, handle)) = OutputStream::try_default() else {
                while let Ok(cmd) = rx.recv() {
                    if let AudioCmd::PlayBytes { done_tx, .. } = cmd {
                        let _ = done_tx.send(Err("No audio output device available".to_string()));
                    }
                }
                return;
            };

            let mut current_sink: Option<Sink> = None;

            while let Ok(cmd) = rx.recv() {
                match cmd {
                    AudioCmd::Stop => {
                        if let Some(sink) = current_sink.take() {
                            sink.stop();
                        }
                    }
                    AudioCmd::PlayBytes { data, done_tx } => {
                        if stop_flag.load(Ordering::Relaxed) {
                            let _ = done_tx.send(Ok(()));
                            continue;
                        }
                        let source = match Decoder::new(Cursor::new(data)) {
                            Ok(src) => src,
                            Err(e) => {
                                let _ = done_tx.send(Err(format!("Audio decode error: {e}")));
                                continue;
                            }
                        };

                        if current_sink.is_none() {
                            match Sink::try_new(&handle) {
                                Ok(s) => current_sink = Some(s),
                                Err(e) => {
                                    let _ = done_tx.send(Err(format!("Sink error: {e}")));
                                    continue;
                                }
                            }
                        }

                        if let Some(sink) = current_sink.as_ref() {
                            sink.append(source);
                            while !sink.empty() {
                                if stop_flag.load(Ordering::Relaxed) {
                                    sink.stop();
                                    current_sink = None;
                                    break;
                                }
                                std::thread::sleep(Duration::from_millis(15));
                            }
                        }
                        let _ = done_tx.send(Ok(()));
                    }
                }
            }
        });
        tx
    })
}

/// Play WAV or MP3 bytes using native Rust rodio continuous audio sink.
#[pyfunction]
pub fn rust_play_audio_bytes(py: Python<'_>, data: &[u8]) -> PyResult<()> {
    let owned = data.to_vec();
    let stop_flag = get_stop_flag();
    stop_flag.store(false, Ordering::Relaxed);
    let tx = get_audio_tx();
    let (done_tx, done_rx) = std::sync::mpsc::channel();
    tx.send(AudioCmd::PlayBytes {
        data: owned,
        done_tx,
    })
    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Audio thread error: {e}")))?;

    py.allow_threads(move || {
        done_rx
            .recv()
            .unwrap_or_else(|e| Err(format!("Audio recv error: {e}")))
    })
    .map_err(pyo3::exceptions::PyRuntimeError::new_err)
}

/// Immediately stop any active Rust rodio audio playback.
#[pyfunction]
pub fn rust_stop_audio() -> PyResult<()> {
    get_stop_flag().store(true, Ordering::Relaxed);
    if let Some(tx) = AUDIO_TX.get() {
        let _ = tx.send(AudioCmd::Stop);
    }
    Ok(())
}

fn build_wav_from_i16(pcm: &[i16], sample_rate: u32) -> Vec<u8> {
    let data_bytes = (pcm.len() * 2) as u32;
    let riff_size = 36 + data_bytes;
    let byte_rate = sample_rate * 2;
    let mut out = Vec::with_capacity(44 + data_bytes as usize);
    out.extend_from_slice(b"RIFF");
    out.extend_from_slice(&riff_size.to_le_bytes());
    out.extend_from_slice(b"WAVE");
    out.extend_from_slice(b"fmt ");
    out.extend_from_slice(&16u32.to_le_bytes()); // PCM chunk size
    out.extend_from_slice(&1u16.to_le_bytes()); // PCM format
    out.extend_from_slice(&1u16.to_le_bytes()); // Mono
    out.extend_from_slice(&sample_rate.to_le_bytes());
    out.extend_from_slice(&byte_rate.to_le_bytes());
    out.extend_from_slice(&2u16.to_le_bytes()); // Block align
    out.extend_from_slice(&16u16.to_le_bytes()); // Bits per sample
    out.extend_from_slice(b"data");
    out.extend_from_slice(&data_bytes.to_le_bytes());
    for &s in pcm {
        out.extend_from_slice(&s.to_le_bytes());
    }
    out
}

fn apply_calm_envelope(pcm: &mut [i16], sample_rate: u32, gain: f32, speech_start_idx: usize) {
    if pcm.is_empty() {
        return;
    }
    let fade_in_len = ((sample_rate as usize * 14) / 1000).min(pcm.len() / 2);
    let fade_out_len = ((sample_rate as usize * 25) / 1000).min(pcm.len() / 2);

    // Apply calm headroom gain (~ -2.8 dBFS) so speech never blasts at 0 dBFS
    for s in pcm.iter_mut() {
        *s = ((*s as f32) * gain).clamp(-32767.0, 32767.0) as i16;
    }

    // Raised-cosine fade-in right at speech onset (eliminates harsh attack / click)
    let fi_start = speech_start_idx.min(pcm.len().saturating_sub(fade_in_len));
    for i in 0..fade_in_len {
        let t = (i as f32) / (fade_in_len.max(1) as f32);
        let env = 0.5 * (1.0 - (std::f32::consts::PI * t).cos());
        pcm[fi_start + i] = ((pcm[fi_start + i] as f32) * env) as i16;
    }

    // Raised-cosine fade-out
    let n = pcm.len();
    for i in 0..fade_out_len {
        let t = (i as f32) / (fade_out_len.max(1) as f32);
        let env = 0.5 * (1.0 + (std::f32::consts::PI * t).cos());
        let idx = n - fade_out_len + i;
        pcm[idx] = ((pcm[idx] as f32) * env) as i16;
    }
}

/// Fast Rust converter: takes raw little-endian float32 PCM bytes, trims harsh digital silence,
/// adds calm pre-roll + exact narrator breath pause, applies cosine fade-in/out & calm headroom.
#[pyfunction]
#[pyo3(signature = (float32_bytes, sample_rate, threshold=0.0005, post_ms=300))]
pub fn float32_to_trimmed_wav<'py>(
    py: Python<'py>,
    float32_bytes: &[u8],
    sample_rate: u32,
    threshold: f32,
    post_ms: u32,
) -> PyResult<Bound<'py, PyBytes>> {
    let count = float32_bytes.len() / 4;
    if count == 0 {
        return Ok(PyBytes::new(py, &build_wav_from_i16(&[], sample_rate)));
    }
    let mut samples = Vec::with_capacity(count);
    for chunk in float32_bytes.chunks_exact(4) {
        samples.push(f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]));
    }

    let first = samples
        .iter()
        .position(|&s| s.abs() >= threshold)
        .unwrap_or(0);
    let last = samples
        .iter()
        .rposition(|&s| s.abs() >= threshold)
        .unwrap_or(samples.len().saturating_sub(1));

    let pre_roll = (sample_rate as usize * 90) / 1000; // 90ms gentle lead-in silence
    let post_target = (sample_rate as usize * post_ms as usize) / 1000;
    let start = first.saturating_sub(pre_roll);
    let existing_tail = samples.len().saturating_sub(last + 1);
    let end = (last + 1 + post_target).min(samples.len());
    let extra_lead = pre_roll.saturating_sub(first);
    let extra_tail = post_target.saturating_sub(existing_tail);

    let slice = if start < end { &samples[start..end] } else { &samples[..] };
    let mut pcm = Vec::with_capacity(extra_lead + slice.len() + extra_tail);
    pcm.resize(extra_lead, 0i16);
    for &s in slice {
        let clamped = s.clamp(-1.0, 1.0);
        pcm.push((clamped * 32767.0) as i16);
    }
    pcm.resize(pcm.len() + extra_tail, 0i16);
    let speech_onset = extra_lead + (first - start);
    apply_calm_envelope(&mut pcm, sample_rate, 0.72, speech_onset);
    let wav = build_wav_from_i16(&pcm, sample_rate);
    Ok(PyBytes::new(py, &wav))
}

/// Fast Rust WAV silence trimmer + calm envelope for Piper's 16-bit mono WAV bytes.
#[pyfunction]
#[pyo3(signature = (wav_bytes, threshold=160, post_ms=300))]
pub fn trim_wav_silence<'py>(
    py: Python<'py>,
    wav_bytes: &[u8],
    threshold: i16,
    post_ms: u32,
) -> PyResult<Bound<'py, PyBytes>> {
    if wav_bytes.len() <= 44 || &wav_bytes[0..4] != b"RIFF" {
        return Ok(PyBytes::new(py, wav_bytes));
    }
    let sample_rate = u32::from_le_bytes([wav_bytes[24], wav_bytes[25], wav_bytes[26], wav_bytes[27]]);
    let channels = u16::from_le_bytes([wav_bytes[22], wav_bytes[23]]);
    if channels != 1 {
        return Ok(PyBytes::new(py, wav_bytes));
    }
    let pcm_bytes = &wav_bytes[44..];
    let mut pcm = Vec::with_capacity(pcm_bytes.len() / 2);
    for ch in pcm_bytes.chunks_exact(2) {
        pcm.push(i16::from_le_bytes([ch[0], ch[1]]));
    }
    if pcm.is_empty() {
        return Ok(PyBytes::new(py, wav_bytes));
    }
    let first = pcm.iter().position(|&s| s.abs() >= threshold).unwrap_or(0);
    let last = pcm.iter().rposition(|&s| s.abs() >= threshold).unwrap_or(pcm.len() - 1);
    let pre_roll = (sample_rate as usize * 90) / 1000;
    let post_target = (sample_rate as usize * post_ms as usize) / 1000;
    let start = first.saturating_sub(pre_roll);
    let existing_tail = pcm.len().saturating_sub(last + 1);
    let end = (last + 1 + post_target).min(pcm.len());
    let extra_lead = pre_roll.saturating_sub(first);
    let extra_tail = post_target.saturating_sub(existing_tail);

    let slice = if start < end { &pcm[start..end] } else { &pcm[..] };
    let mut out_pcm = Vec::with_capacity(extra_lead + slice.len() + extra_tail);
    out_pcm.resize(extra_lead, 0i16);
    out_pcm.extend_from_slice(slice);
    out_pcm.resize(out_pcm.len() + extra_tail, 0i16);
    let speech_onset = extra_lead + (first - start);
    apply_calm_envelope(&mut out_pcm, sample_rate, 0.78, speech_onset);
    let out = build_wav_from_i16(&out_pcm, sample_rate);
    Ok(PyBytes::new(py, &out))
}
