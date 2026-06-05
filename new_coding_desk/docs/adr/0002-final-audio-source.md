# Final 阶段使用后端缓存的完整 PCM 做离线 ASR rescore

`translation_final` 的 source_text 来源是后端缓存的整句 PCM 经过离线 ASR rescore 后的结果，而非流式 ASR 的最后一个 interim partial。

流式 ASR 的 partial 文本可能有重复、缺字和回滚修正。`translation_records` 是会议的历史记录，不应保存不稳定文本。且翻译（MT）依赖 source_text 质量，ASR 错误会传递到译文。

实现上，`TranslationService` 新增 `process_final_array(audio: np.ndarray, sr: int, ...)` 方法，内部调用 `speech.transcribe_array()` 做离线 ASR，然后走现有的翻译→写库→广播流程。旧 HTTP 入口 `process_final_file(audio_path, ...)` 继续接受文件路径，两者共用 `_finalize_text()` 核心逻辑。

保留降级策略：如果离线 ASR 失败，使用最后一次稳定 interim 文本作为 fallback，标记 `source_type = "streaming_fallback"`。
