# 以下は main_window.py の import_voice_bank メソッドの STEP 5 部分の修正版です
# 行番号 3900-3925 付近を置き換えてください

            # --- STEP 5: UIの即時反映（修正版） ---
            v_manager = getattr(self, 'voice_manager', None)
            if v_manager and hasattr(v_manager, 'scan_utau_voices'):
                v_manager.scan_utau_voices()
            
            # 🔴 重要: ボイスギャラリーUIの再構築を実行
            if hasattr(self, 'voice_gallery') and self.voice_gallery is not None:
                # ギャラリーに最新の音源情報を反映
                self.voice_gallery.setup_gallery()
                self.voice_gallery.update()
                print(f"✅ Voice gallery refreshed with {installed_name}")
            else:
                # voice_gallery がまだ初期化されていない場合は新規作成
                print("⚠️ Warning: voice_gallery not initialized, creating new instance")
                if v_manager:
                    self.voice_gallery = VoiceCardGallery(v_manager)
                    self.voice_gallery.set_partner_data(self.confirmed_partners)
                    self.voice_gallery.setup_gallery()
                    self.voice_gallery.voice_selected.connect(self.on_voice_changed)
            
            # 成功通知（ステータスバー）
            msg = f"✅ '{installed_name}' インストール完了！ ({engine_msg})"
            if status_bar:
                status_bar.showMessage(msg, 5000)
            
            # SE再生のエラー(play_se属性なし)を修正
            audio_out = getattr(self, 'audio_output', None)
            if audio_out:
                se_path = get_resource_path("assets/install_success.wav")
                if os.path.exists(se_path):
                    # play_se がない場合は setSource/play など標準的な手段を検討
                    if hasattr(audio_out, 'play_se'):
                        try:
                            audio_out.play_se(se_path)
                        except Exception as e:
                            print(f"DEBUG: play_se failed: {e}")
                    elif hasattr(audio_out, 'setSource'):
                        try:
                            from PySide6.QtCore import QUrl
                            audio_out.setSource(QUrl.fromLocalFile(se_path))
                            if hasattr(audio_out, 'play'):
                                audio_out.play()
                        except Exception as e:
                            print(f"DEBUG: setSource/play failed: {e}")
            
            # メッセージボックスで完了を表示
            QMessageBox.information(
                self, 
                "導入成功", 
                f"音源 '{installed_name}' をインストールしました。\n"
                f"エンジン: {engine_msg}\n\n"
                f"キャラクター選択パネルから選択できます。"
            )
