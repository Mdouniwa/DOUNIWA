/**
 * サーバー設定。すべて環境変数で差し替え可能にする(モデルIDは特に改廃が速いため)。
 * 必須: GEMINI_API_KEY(課金有効なプロジェクトのGemini APIキー)。
 */

// server/.env があれば読み込む(Node 20.6+ 標準機能。dotenv不要)
try {
  process.loadEnvFile(new URL('../.env', import.meta.url).pathname);
} catch {
  // .env が無ければ環境変数のみで動く(launchd の EnvironmentVariables など)
}

function required(name: string): string {
  const v = process.env[name];
  if (!v) {
    throw new Error(
      `環境変数 ${name} が設定されていません。server/.env.example を参考に設定してください。`,
    );
  }
  return v;
}

export const config = {
  /** n8n(5678)・Dify(80/3000/5001)と衝突しないポート */
  port: Number(process.env.PORT || 8788),

  /** CORS許可オリジン(カンマ区切り)。未設定なら全許可(Tailscale内前提) */
  corsOrigins: process.env.CORS_ORIGINS?.split(',').map((s) => s.trim()) ?? null,

  geminiApiKey: () => required('GEMINI_API_KEY'),

  // --- 使用モデル(用途別・環境変数で差し替え可) ---
  /** 対話・質問生成: 低レイテンシ重視で子どもを待たせない */
  chatModel: process.env.CHAT_MODEL || 'gemini-3.5-flash-lite',
  /** 物語生成: 起承転結の構成力が要る */
  storyModel: process.env.STORY_MODEL || 'gemini-3.6-flash',
  /** 挿絵生成: Nano Banana 2(参照画像方式でキャラクター一貫性を保つ) */
  imageModel: process.env.IMAGE_MODEL || 'gemini-3.1-flash-image',
  /** 音声合成: 感情表現を自然言語で指示できる日本語高品質TTS */
  ttsModel: process.env.TTS_MODEL || 'gemini-3.1-flash-tts-preview',
  /**
   * TTSのプリセット声。落ち着いた大人の女性声(公式説明: Gentle)。
   * 候補比較: Leda=194Hz(幼め) / Sulafat=218Hz / Achernar=222Hz / Vindemiatrix=168Hz
   * → 最も低く穏やかな Vindemiatrix を既定にする(儚げな妖精のビジュアルに合わせる)
   */
  ttsVoice: process.env.TTS_VOICE || 'Vindemiatrix',
  /** TTSの話し方指示(文頭に付ける自然言語スタイル。読み上げられない) */
  ttsStyle:
    process.env.TTS_STYLE ||
    'やさしく、おだやかに、少し低めの落ち着いたトーンで、ゆっくり温かく はなしかける こえで いってください',
} as const;
