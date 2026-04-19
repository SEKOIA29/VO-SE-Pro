class LicenseManager:
    # --- [リリース時に操作する変数] ---
    # サーバーができるまでは False で配布。
    # 準備ができたら、ここを「サーバーに問い合わせるロジック」に書き換える。
    INTERNAL_PRO_FLAG = False 

    @classmethod
    def is_pro(cls):
        # 現時点ではこの内部フラグのみを返す
        return cls.INTERNAL_PRO_FLAG

    @classmethod
    def get_license_type_name(cls):
        return "Professional" if cls.is_pro() else "Free Edition"
