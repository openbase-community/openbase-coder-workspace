import { describeAudioRouting, playCalibrationPhrase } from "./audioOutput.js";

console.log(describeAudioRouting());
console.log("Playing calibration phrase with Cartesia TTS through Mac speakers...");
await playCalibrationPhrase();
console.log("Audio calibration phrase completed.");
