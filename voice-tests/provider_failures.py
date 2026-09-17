"""Whitelist provider failures without copying raw tracebacks or credentials."""


def failure_record(record):
    message = record.get("message", "")
    stage = None
    fields = {}
    if message.startswith("TTS failed after partial audio was already sent"):
        stage = "tts_provider_partial_failure"
        value = record.get("pushed_duration")
        if isinstance(value, (int, float)):
            fields["audio_seconds"] = value
    elif message.startswith("Error in _tts_inference_task"):
        stage = "tts_provider_inference_failure"
    elif message.startswith("Cartesia connection error"):
        stage = "tts_provider_connection_failure"
    elif message.startswith("failed to synthesize speech:"):
        stage = "tts_provider_retry"
    elif message.startswith("failed to recognize speech:"):
        stage = "stt_provider_retry"
    elif message.startswith("AssemblyAI WebSocket closed unexpectedly"):
        stage = "stt_provider_connection_closed"
    elif message.startswith("AgentSession is closing due to unrecoverable error"):
        stage = "voice_session_unrecoverable_failure"
    elif "AgentSession closed after an unrecoverable pipeline error; exiting" in message:
        stage = "voice_worker_recovery_exit"
    if stage is None:
        return None
    if isinstance(record.get("attempt"), int):
        fields["attempt"] = record["attempt"]
    return {"timestamp": record["timestamp"], "message":
        "dispatch_timing stage=" + stage + "".join(f" {key}={value}" for key, value in fields.items())}
