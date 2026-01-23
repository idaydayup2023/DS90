
# Architecture

Based on the latest design (2026-01), the system adopts a layered architecture separating triggers, routing (MCP), agents, skills, and external services.

```mermaid
flowchart TB 
 
     %% ========= Trigger Layer ========= 
     subgraph TriggerLayer["事件 / 触发层"] 
         Timer["定时触发"] 
         Manual["人工触发"] 
     end 
 
     %% ========= MCP Runtime ========= 
     subgraph MCPLayer["MCP 运行层（Agent 路由）"] 
         MCP["MCP Router"] 
         Rules["路由规则（配置）"] 
     end 
 
     %% ========= Agent Layer ========= 
     subgraph AgentLayer["Agent 层（决策与编排）"] 
         ftpAgent["FTP Agent"] 
         ffmpegAgent["FFmpeg Agent"] 
         imdbAgent["IMDB Agent"] 
         srtAgent["SRT Agent"] 
         translateAgent["Translate Agent"] 
         translateQCAgent["Translate QC Agent"] 
         srtACKAgent["SRT ACK Agent"] 
         migrateAgent["Migrate Agent"] 
     end 
 
     %% ========= Skill Layer ========= 
     subgraph SkillLayer["Skill 层（能力执行）"] 
         ftpSkill["FTP_OpSkill"] 
         ffmpegSkill["FFmpeg_OpSkill"] 
         imdbSkill["IMDB_OpSkill"] 
         translateSkill["SRT_TranslateSkill"] 
         migrateSkill["MigrateSkill"] 
         cleanSkill["CleanSkill"] 
         asrSkill["ASR Skill"] 
         ocrSkill["OCR Skill"] 
     end 
 
     %% ========= External / Model Layer ========= 
     subgraph ExternalLayer["外部服务 / 模型"] 
         ftpServer["FTP Server"] 
         ffmpegCli["FFmpeg CLI"] 
         imdbAPI["IMDB API"] 
         whisperModel["Whisper ASR"] 
         ollamaModel["Ollama LLM"] 
         tesseractOCR["Tesseract OCR"] 
     end 
 
     %% ========= Trigger Flow ========= 
     Timer --> MCP 
     Manual --> MCP 
     Rules --> MCP 
 
     %% ========= MCP -> Agent Routing ========= 
     MCP <--> ftpAgent 
     MCP <--> ffmpegAgent 
     MCP <--> imdbAgent 
     MCP <--> srtAgent 
     MCP <--> translateAgent 
     MCP <--> migrateAgent 
 
     %% ========= Agent -> Skill ========= 
     ftpAgent --> ftpSkill 
     ffmpegAgent --> ffmpegSkill 
     imdbAgent --> imdbSkill 
 
     srtAgent --> asrSkill 
     srtAgent --> ocrSkill 
 
     translateAgent --> translateSkill 
     translateQCAgent --> translateAgent 
     srtACKAgent --> translateAgent 
 
     migrateAgent --> migrateSkill 
     migrateAgent --> cleanSkill 
 
     %% ========= Skill -> External ========= 
     ftpSkill --> ftpServer 
     ffmpegSkill --> ffmpegCli 
     imdbSkill --> imdbAPI 
     imdbSkill --> ollamaModel 
 
     asrSkill --> whisperModel 
     ocrSkill --> tesseractOCR 
 
     translateSkill --> ollamaModel 
     migrateSkill --> ollamaModel
```

## Layers Description

1.  **Trigger Layer**: Entry points. `Timer` corresponds to `cron` jobs (e.g. `cron_scan.sh`), `Manual` corresponds to CLI execution.
2.  **MCP Runtime**: The central orchestration logic (currently implemented in `orchestrator.py` and `runner.py`). It reads `config.json` (Rules) and routes tasks.
3.  **Agent Layer**: Logical units responsible for decision making.
    *   `srtAgent`: Handles subtitle acquisition (embedded, external, ASR, OCR).
    *   `translateAgent`: Manages the translation process (LLM calls, batching).
    *   `migrateAgent`: Handles file organization and cleaning (`dir_migrate` module).
4.  **Skill Layer**: Atomic capabilities or "Tools" (MCPs).
    *   `FTP_OpSkill`: `FtpMcp`
    *   `FFmpeg_OpSkill`: `MediaMcp`
    *   `IMDB_OpSkill`: `ImdbMcp`
    *   `ASR Skill`: `AsrMcp`
    *   `OCR Skill`: `PgsOcrMcp`
    *   `TranslateSkill`: `OllamaMcp` / `translation.py`
5.  **External Layer**: Actual binaries or services (`ffmpeg`, `ollama`, `tesseract`, etc.).
