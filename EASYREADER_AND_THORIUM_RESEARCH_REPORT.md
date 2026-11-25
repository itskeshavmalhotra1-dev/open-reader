# Research Report: How Dolphin EasyReader and Thorium Reader Work

**Prepared for:** `d:\projects\book reader` (Future Book Reader Reference)  
**Date:** 2026-11-25  

---

## Executive Summary

**Dolphin EasyReader** and **Thorium Reader** are two of the leading accessible digital book readers globally, built with very different business models, technical stacks, and ecosystem priorities:

- **Dolphin EasyReader** (by Dolphin Computer Access) is a **proprietary, cross-platform** application (iOS, Android, Windows, macOS, Amazon Fire) designed primarily around **direct integration with 40–50+ global accessible libraries** (such as Bookshare, RNIB Bookshare, NLS BARD, CELA, Vision Australia, and Sugamya Pustakalaya), **rich synchronized Read-Along TTS** (SAPI5, Microsoft OneCore, and mobile native voices), and **dyslexia/low-vision customization**.
- **Thorium Reader** (by EDRLab — European Digital Reading Lab) is a **100% free, open-source desktop application** (Windows, macOS, Linux, with expanding mobile/web siblings) built on **Electron, React, Redux/Redux-Saga, and the Readium Desktop (Readium 2) toolkits**. It is widely regarded as the gold standard for **desktop screen-reader accessibility (NVDA, JAWS, Narrator, VoiceOver)**, **open web standards**, **OPDS 1.x/2.x catalogs**, and **Readium LCP DRM**.

---

## 1. Dolphin EasyReader — How It Works

### 1.1 Core Workflow
1. **Library Acquisition:** Users sign into their Dolphin account (or Google account) and connect directly to supported accessible library accounts inside the app. Books are searched, downloaded, and organized into a personal bookshelf.
2. **Parsing & Structure Extraction:** EasyReader parses structured formats (DAISY, EPUB, HTML, DOCX) and semi-structured/plain formats (TXT, clipboard text, restricted PDFs) into an internal navigable text/structure tree (headings, paragraphs, lists, tables, page numbers, and MathML).
3. **Multi-Modal Rendering:**
   - **Visual:** Renders text with user-configured fonts (including OpenDyslexic), spacing, color themes, and focus masks.
   - **Auditory:** Drives either pre-recorded human audio (DAISY audiobooks) or synthetic TTS voices (Microsoft OneCore, SAPI5 on Windows; native voices on iOS/Android).
   - **Tactile / Assistive Tech:** Exposes UI and reading content to OS screen readers (NVDA, JAWS, VoiceOver, TalkBack) and refreshable Braille displays.

### 1.2 Architecture Overview (Modular Layers)
Because EasyReader is closed-source, exact internal class names are proprietary, but its public technical behavior and integrations reflect four core layers:
- **Library Connector Layer:** Integrates with global talking-book libraries using **DAISY Online Delivery Protocol (DODP)**, **Bookshare API**, and OAuth/REST connectors. Handles authentication, bookshelf sync, and downloading.
- **Parsing & Formatting Engine:** Extracts semantic structure from DAISY 2/3, EPUB 2/3 (DRM-free), DOCX, HTML, TXT, and MathML.
- **Synchronization Engine:** Maps time-aligned audio metadata (**SMIL** files in DAISY and **Media Overlays** in EPUB 3) or TTS word-boundary callbacks directly to text nodes, enabling synchronized word-by-word and sentence-by-sentence highlighting.
- **Accessibility Bridge:** Integrates with Windows screen readers (NVDA, JAWS), Apple VoiceOver, and Android TalkBack, plus a dedicated **Linear Reading Mode** to keep screen reader and Braille display navigation predictable.

### 1.3 Supported Formats
- **DAISY:** DAISY 2 and DAISY 3 (text-only, audio-only, and synchronized full-text/full-audio). Supports hierarchical heading navigation, skippable elements (footnotes, page numbers, image descriptions), and print page jumps.
- **EPUB:** EPUB 2 and EPUB 3 (DRM-free), respecting HTML5 semantics and ARIA landmarks.
- **Documents & Text:** Microsoft Word (`.docx`), HTML, plain text (`.txt`), and direct clipboard text.
- **Math:** **MathML** rendering and spoken math support.
- **Audio & PDF:** MP3 audiobooks and restricted PDFs (such as those provided via RNIB Bookshare).

### 1.4 Text-to-Speech (TTS) & Synchronization
- **Windows Voice Engines:** Supports both **SAPI5** (third-party voices like Ivona, Vocalizer) and **Microsoft OneCore** voices built into Windows 10/11.
- **Controls:** Granular speed (e.g., 5% increments), pitch, volume, and custom pronunciation rules.
- **Skippable Content:** Users can configure whether the TTS engine announces or skips footnotes, page numbers, and image descriptions.
- **Read-Along Highlighting & Focus Mode:** Highlights the active word, sentence, or line during playback, with optional line masking/dimming for dyslexia and ADHD.

### 1.5 Cloud Sync & Licensing
- **Free Tier:** Core reading, local files, and library access are free (with a Dolphin/Google sign-in).
- **EasyReader Premium:** Optional paid subscription adding cross-device cloud sync for bookshelves, reading positions, bookmarks, and notes.

---

## 2. Thorium Reader (EDRLab) — How It Works

### 2.1 Core Philosophy
Thorium Reader follows a **"Bring Your Own Books"** model built entirely on **open web standards** and **open-source software** (BSD-3-Clause). It requires no mandatory user account, protects user privacy, and avoids proprietary DRM ecosystems like Adobe Digital Editions in favor of **Readium LCP**.

### 2.2 Software Architecture
Thorium Reader is a cross-platform desktop app (**Windows, macOS, Linux**, supporting both `x64` and `arm64`) built on:

1. **Application Shell:**
   - **Electron & Node.js:** Main process handles file system access, ZIP/EPUB unpacking, local HTTP streaming, LCP decryption, and OS integrations; Chromium renderer processes display the UI and book content.
   - **TypeScript & React:** UI layer (Bookshelf, Catalogs, Settings, Reader chrome).
   - **Redux & Redux-Saga:** Global state management (library metadata, reading positions, themes, OPDS feeds) with Redux-Saga orchestrating asynchronous side effects (file I/O, IPC between main and renderer processes, decryption).

2. **The Readium Desktop / Readium 2 (R2) Architecture:**
   Thorium is powered by modular Readium libraries (`r2-shared-js`, `r2-streamer-js`, `r2-navigator-js`, `r2-lcp-js`, `r2-opds-js`):
   - **The Streamer (`r2-streamer-js`):** Runs in the backend/main process. It parses packaged publications (EPUB, DAISY, Audiobook, Divina, PDF), handles LCP decryption/deobfuscation via its **Fetcher**, injects **ReadiumCSS** and helper scripts into HTML resources, and serves them over a local internal HTTP server.
   - **Readium Web Publication Manifest (RWPM):** A standardized JSON manifest (`r2-shared-js`) that normalizes *every* supported format (EPUB, DAISY, PDF, Audiobook, Divina) into a uniform model (`metadata`, `readingOrder`/`spine`, `toc`, `resources`).
   - **The Navigator (`r2-navigator-js`):** Controls the reading viewport inside Chromium—handling pagination vs. scrolling, text selection, bookmarks, annotations, and dynamic layout recalculation via **ReadiumCSS**.

### 2.3 Supported Formats & DRM
- **EPUB 2 & EPUB 3:** Full support for both reflowable and fixed-layout EPUBs, including EPUB 3 Media Overlays and interactive scripting.
- **DAISY 2.02 & DAISY 3:** Supports DAISY packages (`.zip` or unzipped folders containing `.opf`/`.xml` navigation) by normalizing them into the Readium publication model.
- **PDF:** Native PDF viewing powered by Mozilla's **`pdf.js`** integrated into the RWPM **PDF Profile** (`https://readium.org/webpub-manifest/profiles/pdf`). Supports Tagged PDFs by mapping structural tags and text layers to DOM/ARIA elements for screen readers.
- **MathML / STEM:** Integrates **MathJax** (opt-in/dynamic) to render complex MathML equations visually and expose accessible semantics to screen readers like NVDA and JAWS.
- **Audiobooks & Comics:** W3C/Readium Audiobooks (`.audiobook`), MP3 collections, and Divina/CBZ comics/manga.
- **Readium LCP (Licensed Content Protection):** Open, privacy-respecting DRM (`.lcpl` files) widely used by public libraries and academic platforms.

### 2.4 Screen Reader & Accessibility Architecture
Thorium is engineered specifically to pass rigorous desktop accessibility benchmarks (including EPUBTest):
- **Chromium Accessibility Tree Bridge:** Exposes book content via **Microsoft UI Automation (UIA)** / **IAccessible2** on Windows and macOS Accessibility APIs.
- **Browse Mode / Virtual Cursor Support:** Because EPUB chapters are rendered as HTML inside an `iframe`/WebView, screen readers (NVDA, JAWS, Narrator, VoiceOver) treat the book as a live web document—allowing standard navigation shortcuts (`H` for headings, `K` for links, arrow keys for line-by-line reading).
- **"Enhance Screen Reader Experience" Setting:** An explicit toggle in Thorium's General Settings that optimizes focus management, ARIA roles, landmark structure, and DOM updates across `iframe` boundaries so screen readers do not get trapped or lose linear flow when turning pages or jumping from the Table of Contents.
- **Keyboard-First Design:** Full keyboard navigation across the Bookshelf, OPDS catalogs, Settings, Annotations, and Reader views, with customizable keyboard shortcuts.
- **Global Scripts:** Full support for Right-to-Left (RTL) languages (Arabic, Hebrew) and vertical writing modes (e.g., Japanese), including mirrored UI and annotation margins.

### 2.5 Thorium 3.0 / 3.1 Key Features
- **Advanced Annotations:** Highlights, underlines, strikethroughs, outlines, custom tags, quick-annotation mode, and a paginated annotations list.
- **Read Aloud (TTS):** Built-in synchronized TTS supporting continuous reading and sentence-by-sentence navigation, plus EPUB 3 Media Overlays.
- **OPDS 1.x & 2.x:** Connect directly to Calibre, Kavita, Komga, and library OPDS catalogs to browse, authenticate, and download books.

---

## 3. Side-by-Side Comparison

| Dimension | Dolphin EasyReader | Thorium Reader |
| :--- | :--- | :--- |
| **Developer** | Dolphin Computer Access | EDRLab (European Digital Reading Lab) |
| **License & Cost** | Proprietary; Free core + paid Premium sync | 100% Free & Open Source (BSD-3-Clause) |
| **Primary Platforms** | Mobile-first (iOS, Android, Fire) + Windows/macOS | Desktop-first (Windows, macOS, Linux) + iOS |
| **Core Tech Stack** | Closed-source native/hybrid apps per OS | Electron, Node.js, TypeScript, React, Redux/Saga, Readium 2 |
| **DRM Support** | DRM-free + library-authorized downloads (e.g., Bookshare) | **Readium LCP** + DRM-free |
| **Library Protocols** | Direct login to 40–50+ libraries (DODP, Bookshare API) | **OPDS 1.x & 2.x** catalogs |
| **Formats** | DAISY 2/3, EPUB 2/3, DOCX, TXT, HTML, MathML, MP3, restricted PDF | EPUB 2/3, DAISY 2.02/3, PDF (`pdf.js`), Audiobooks, Divina/CBZ, MathML |
| **Screen Readers** | Strong on mobile (VoiceOver/TalkBack) + Braille; Linear Mode | Gold standard on desktop (**NVDA, JAWS, Narrator, VoiceOver**) |
| **TTS Engine** | SAPI5, Microsoft OneCore, mobile native; word/sentence sync | OS speech synthesis + EPUB Media Overlays; continuous & sentence mode |
| **Dyslexia / Low Vision** | Market-leading spacing, line masks, contrast, OpenDyslexic | Strong ReadiumCSS themes, 10+ fonts, spacing, column control |

---

## 4. Key Architectural Takeaways for Building a Future Book Reader

If building a new accessible book reader in `d:\projects\book reader`, the combined lessons from EasyReader and Thorium Reader point to the following high-value design principles:

1. **Normalize All Formats to a Unified Internal Manifest (Thorium/RWPM Pattern):**
   Instead of writing separate UI/navigation logic for EPUB, DAISY, DOCX, and PDF, convert or map every imported publication into a single internal manifest model (metadata, reading order/spine, table of contents, page list, and resource fetcher).
2. **Treat Screen Reader & TTS Modes as First-Class Citizens:**
   - **For Screen Reader Users (NVDA/JAWS/VoiceOver):** Render HTML-based books cleanly so Browse Mode / Virtual Cursor works naturally, manage focus explicitly when jumping via Table of Contents or turning chapters across `iframe`/WebView boundaries, and provide an "Enhance Screen Reader Experience" mode (or clean semantic DOM without visual pagination hacks interfering with the accessibility tree).
   - **For Self-Voicing TTS Users:** Support native OS voices (**Microsoft OneCore** and **SAPI5** on Windows, `AVSpeechSynthesizer` on Apple, Android TTS), word/sentence-boundary highlighting, and **skippable content rules** (footnotes, page numbers, image alt-text).
3. **Support Synchronized Media (SMIL / Media Overlays):**
   For DAISY 2.02/3 and EPUB 3 books with human narration, build a synchronization layer that maps SMIL timestamps to DOM element IDs.
4. **Handle PDFs Carefully:**
   Standard canvas-only PDF rendering is completely inaccessible. Use a text-layer + structure-tree approach (like `pdf.js` Tagged PDF extraction) so headings, reading order, and paragraphs are exposed to assistive technology.
5. **Open Library & Accessible Library Protocols:**
   Supporting **OPDS 1.x/2.x** covers self-hosted libraries (Calibre, Kavita, Komga) and public catalogs, while **DODP (DAISY Online)** / **Bookshare API** support unlocks specialized accessible libraries.
6. **Complete Keyboard Operability:**
   Every action—bookshelf management, TOC navigation, bookmarks, annotations, TTS playback, and visual theme settings—must be reachable via standard keyboard navigation and documented shortcuts without mouse dependency.
