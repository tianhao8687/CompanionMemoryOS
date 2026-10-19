/* Library-only Android acceptance probe. Uses the same pinned model, native
 * library and decoder settings as local_asr_worker.dart; it is not an APK. */
#include "sherpa-onnx/c-api/c-api.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

static double now_ms(void) {
  struct timespec time;
  clock_gettime(CLOCK_MONOTONIC, &time);
  return time.tv_sec * 1000.0 + time.tv_nsec / 1000000.0;
}

int main(int argc, char **argv) {
  if (argc < 3 || argc > 82) return 2;
  char encoder[1024], decoder[1024], joiner[1024], tokens[1024];
  snprintf(encoder, sizeof(encoder), "%s/encoder-epoch-99-avg-1.int8.onnx", argv[1]);
  snprintf(decoder, sizeof(decoder), "%s/decoder-epoch-99-avg-1.onnx", argv[1]);
  snprintf(joiner, sizeof(joiner), "%s/joiner-epoch-99-avg-1.int8.onnx", argv[1]);
  snprintf(tokens, sizeof(tokens), "%s/tokens.txt", argv[1]);
  SherpaOnnxOnlineRecognizerConfig config = {0};
  config.feat_config.sample_rate = 16000;
  config.feat_config.feature_dim = 80;
  config.model_config.transducer.encoder = encoder;
  config.model_config.transducer.decoder = decoder;
  config.model_config.transducer.joiner = joiner;
  config.model_config.tokens = tokens;
  config.model_config.num_threads = 2;
  config.model_config.provider = "cpu";
  config.model_config.model_type = "zipformer";
  config.decoding_method = "modified_beam_search";
  config.max_active_paths = 4;
  config.enable_endpoint = 1;
  config.rule1_min_trailing_silence = 2.4;
  config.rule2_min_trailing_silence = 0.8;
  config.rule3_min_utterance_length = 20;
  double start = now_ms();
  const SherpaOnnxOnlineRecognizer *recognizer = SherpaOnnxCreateOnlineRecognizer(&config);
  if (!recognizer) return 3;
  double loaded = now_ms();
  for (int file = 2; file < argc; ++file) {
  const SherpaOnnxWave *wave = SherpaOnnxReadWave(argv[file]);
  if (!wave || wave->sample_rate != 16000) {
    if (wave) SherpaOnnxFreeWave(wave);
    SherpaOnnxDestroyOnlineRecognizer(recognizer);
    return 4;
  }
  double stream_start = now_ms();
  const SherpaOnnxOnlineStream *stream = SherpaOnnxCreateOnlineStream(recognizer);
  double stream_ms = now_ms() - stream_start;
  if (!stream) { SherpaOnnxFreeWave(wave); SherpaOnnxDestroyOnlineRecognizer(recognizer); return 5; }
  char transcript[12000] = {0};
  double decoding = now_ms();
  for (int offset = 0; offset < wave->num_samples; offset += 3200) {
    int count = wave->num_samples - offset;
    if (count > 3200) count = 3200;
    SherpaOnnxOnlineStreamAcceptWaveform(stream, 16000, wave->samples + offset, count);
    while (SherpaOnnxIsOnlineStreamReady(recognizer, stream)) SherpaOnnxDecodeOnlineStream(recognizer, stream);
    if (SherpaOnnxOnlineStreamIsEndpoint(recognizer, stream)) {
      const SherpaOnnxOnlineRecognizerResult *result = SherpaOnnxGetOnlineStreamResult(recognizer, stream);
      if (result && result->text && result->text[0]) {
        strncat(transcript, result->text, sizeof(transcript) - strlen(transcript) - 2);
        strcat(transcript, "\n");
      }
      SherpaOnnxDestroyOnlineRecognizerResult(result);
      SherpaOnnxOnlineStreamReset(recognizer, stream);
    }
  }
  float tail[12800] = {0};
  SherpaOnnxOnlineStreamAcceptWaveform(stream, 16000, tail, 12800);
  SherpaOnnxOnlineStreamInputFinished(stream);
  while (SherpaOnnxIsOnlineStreamReady(recognizer, stream)) SherpaOnnxDecodeOnlineStream(recognizer, stream);
  const SherpaOnnxOnlineRecognizerResult *result = SherpaOnnxGetOnlineStreamResult(recognizer, stream);
  if (result && result->text) strncat(transcript, result->text, sizeof(transcript) - strlen(transcript) - 1);
  struct rusage usage;
  getrusage(RUSAGE_SELF, &usage);
  printf("sample=%s\nversion=%s\nload_ms=%.3f\nstream_ms=%.3f\ndecode_ms=%.0f\naudio_seconds=%.3f\npeak_rss_kib=%ld\ntext=%s\nEND_SAMPLE\n",
    argv[file], SherpaOnnxGetVersionStr(), file == 2 ? loaded-start : 0.0, stream_ms, now_ms()-decoding,
    wave->num_samples / 16000.0, usage.ru_maxrss, transcript);
  SherpaOnnxDestroyOnlineRecognizerResult(result);
  SherpaOnnxDestroyOnlineStream(stream);
  SherpaOnnxFreeWave(wave);
  }
  SherpaOnnxDestroyOnlineRecognizer(recognizer);
  return 0;
}
