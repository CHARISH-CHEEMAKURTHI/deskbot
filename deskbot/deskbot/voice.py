"""Voice: "hey celebi" -> speech-to-text -> the same actions and chat as
every other channel -> spoken reply.

Ported from the celebi prototype (openWakeWord + Whisper + pyttsx3), but
wired into deskbot's existing pipeline rather than its own command table:
a recognised utterance goes through intent.classify() exactly like a typed
"Ask deskbot..." request, so actions, the confirmation dialogs, and the
conversational fallback all behave identically no matter how you asked.

Off by default (`voice_enabled`), and every heavy import lives inside a
function -- the voice extras are a big dependency tree (PyAudio, Whisper,
openWakeWord), so a deskbot install that doesn't want them still starts
and runs normally. See requirements-voice.txt.
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import intent as intent_mod
from . import memory

MEMORY_KEY = "voice"
DEPS_HINT = "install the voice extras: pip install -r requirements-voice.txt"

BUNDLED_MODEL = Path(__file__).parent / "assets" / "hey_celebi.onnx"


REQUIRED = [
    ("openwakeword", "openwakeword"),
    ("pyaudio", "PyAudio"),
    ("speech_recognition", "SpeechRecognition"),
    ("whisper", "openai-whisper"),
    ("pyttsx3", "pyttsx3"),
    ("numpy", "numpy"),
]


def wake_word_model_path(cfg) -> Path:
    """Configured wake-word model, else the one bundled with deskbot."""
    configured = getattr(cfg, "wake_word_model", "") or ""
    return Path(configured).expanduser() if configured else BUNDLED_MODEL


def missing_requirements(cfg) -> list[str]:
    """What's stopping voice from working, as human-readable names. Checked
    up front so nothing claims to be listening when it can't be -- the
    listener thread would otherwise die on an import after start() had
    already handed back a live-looking thread."""
    missing = []
    for module, package in REQUIRED:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    model = wake_word_model_path(cfg)
    if not model.exists():
        missing.append(f"wake-word model at {model}")
    return missing


def speak(cfg, text: str) -> bool:
    """Say `text` out loud. Returns False if TTS isn't usable, so callers
    can fall back to the speech bubble alone."""
    if not text or not getattr(cfg, "speak_replies", True):
        return False
    try:
        import pyttsx3
    except ImportError:
        print(f"[deskbot] can't speak -- {DEPS_HINT}")
        return False

    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", int(getattr(cfg, "tts_rate", 150)))
        voices = engine.getProperty("voices")
        index = int(getattr(cfg, "tts_voice_index", 1))
        if voices and 0 <= index < len(voices):
            engine.setProperty("voice", voices[index].id)
        engine.say(text)
        engine.runAndWait()
        return True
    except Exception as exc:
        # espeak missing, no audio sink, a busy device -- never take the
        # listener thread down over it.
        print(f"[deskbot] text-to-speech failed: {exc}")
        return False


def transcribe_once(cfg) -> str | None:
    """Record one utterance from the default mic and transcribe it."""
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            audio = recognizer.listen(
                source, timeout=float(getattr(cfg, "listen_timeout", 10.0))
            )
    except sr.WaitTimeoutError:
        return None
    except OSError as exc:
        print(f"[deskbot] microphone unavailable: {exc}")
        return None

    try:
        text = recognizer.recognize_whisper(
            audio, model=getattr(cfg, "stt_whisper_model", "base"), language="english"
        )
    except Exception as exc:
        print(f"[deskbot] transcription failed: {exc}")
        return None
    text = (text or "").strip()
    return text or None


def handle_utterance(cfg, bridge, text: str) -> str | None:
    """Route one recognised utterance. Same two-way split as WhatsApp:
    a confident action goes through the GUI bridge (so risky ones still get
    their confirmation dialog), anything else becomes conversation."""
    if not text:
        return None

    try:
        parsed = intent_mod.classify(cfg, text)
    except Exception as exc:
        reply = f"something went wrong: {exc}"
        bridge.say_async(reply)
        return reply

    threshold = float(getattr(cfg, "chat_action_confidence", 0.6))
    if parsed is not None and parsed.intent != "unknown" and parsed.confidence >= threshold:
        reply = bridge.run_action_blocking(parsed, via="voice")
    else:
        try:
            reply = intent_mod.chat(cfg, memory.load(MEMORY_KEY), text)
        except Exception as exc:
            reply = f"something went wrong: {exc}"
        bridge.say_async(reply)

    memory.append(cfg, MEMORY_KEY, text, reply)
    return reply


class VoiceListener(threading.Thread):
    """Waits for the wake word, then records, transcribes, acts, replies."""

    def __init__(self, cfg, bridge):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.bridge = bridge
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            import numpy as np
            import pyaudio
            from openwakeword.model import Model
        except ImportError as exc:
            print(f"[deskbot] voice disabled -- {exc}. To enable it, {DEPS_HINT}")
            return

        model_path = wake_word_model_path(self.cfg)
        if not model_path.exists():
            print(f"[deskbot] voice disabled -- wake-word model not found at {model_path}")
            return

        try:
            oww = Model(wakeword_models=[str(model_path)], inference_framework="onnx")
        except Exception as exc:
            print(f"[deskbot] voice disabled -- could not load {model_path}: {exc}")
            return

        audio_in = None
        stream = None
        try:
            audio_in = pyaudio.PyAudio()
            stream = audio_in.open(
                rate=16000,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=1280,
            )
        except Exception as exc:
            print(f"[deskbot] voice disabled -- no usable microphone: {exc}")
            if audio_in is not None:
                audio_in.terminate()
            return

        key = model_path.stem
        threshold = float(getattr(self.cfg, "wake_threshold", 0.3))
        print(f"[deskbot] listening for the wake word ({key})")

        try:
            while not self._stop.is_set():
                frame = stream.read(1280, exception_on_overflow=False)
                if not getattr(self.cfg, "voice_enabled", False):
                    continue  # muted from the menu; keep the stream warm

                scores = oww.predict(np.frombuffer(frame, dtype=np.int16))
                # The score key is the model name; fall back to the best of
                # whatever it did report rather than KeyError-ing on a model
                # whose internal name doesn't match its filename.
                score = scores.get(key)
                if score is None:
                    score = max(scores.values()) if scores else 0.0
                if score <= threshold:
                    continue

                self.bridge.say_async("listening...")
                # Free the mic: SpeechRecognition opens its own stream, and
                # two streams on one device fails on plenty of setups.
                stream.stop_stream()
                try:
                    text = transcribe_once(self.cfg)
                finally:
                    stream.start_stream()
                    oww.reset()  # drop buffered audio so we don't re-trigger

                if not text:
                    continue
                print(f"[deskbot] heard: {text}")
                reply = handle_utterance(self.cfg, self.bridge, text)
                if reply:
                    speak(self.cfg, reply)
        except Exception as exc:  # pragma: no cover - device/runtime failures
            print(f"[deskbot] voice listener stopped: {exc}")
        finally:
            try:
                stream.close()
            finally:
                audio_in.terminate()


def start(cfg, bridge) -> VoiceListener | None:
    """Starts the listener thread. Returns None -- and says why -- if voice
    is switched off or can't actually run, so callers never report success
    for a listener that's about to die on a missing import."""
    if not getattr(cfg, "voice_enabled", False):
        return None

    missing = missing_requirements(cfg)
    if missing:
        print(f"[deskbot] voice unavailable -- missing {', '.join(missing)}. {DEPS_HINT}")
        return None

    listener = VoiceListener(cfg, bridge)
    listener.start()
    return listener
