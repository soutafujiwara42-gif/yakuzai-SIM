import os
import glob
import math
import re
import warnings
import pandas as pd

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_A_DIR = os.path.join(BASE_DIR, "マスタデータ", "薬価基準収載品目リスト")
DATA_B_DIR = os.path.join(BASE_DIR, "マスタデータ", "長期収載品選定療養対象品目リスト")
DATA_C_DIR = os.path.join(BASE_DIR, "マスタデータ", "用法マスタ")


# ----------------------------------------------------------
# ユーティリティ
# ----------------------------------------------------------

def get_files(folder, pattern):
    files = glob.glob(os.path.join(folder, pattern))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    return sorted(files)


def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).replace("\n", "").replace("\r", "").strip()


def clean_code(value):
    if pd.isna(value):
        return ""
    s = str(value).strip().replace(".0", "")
    s = re.sub(r"[^0-9A-Za-z]", "", s)
    return s.upper()


def to_number(value):
    if isinstance(value, pd.Series):
        return pd.to_numeric(
            value.astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("円", "", regex=False)
            .str.replace("－", "", regex=False)
            .str.replace("-", "", regex=False),
            errors="coerce",
        ).fillna(0)
    try:
        return float(
            str(value)
            .replace(",", "")
            .replace("円", "")
            .replace("－", "")
            .replace("-", "")
        )
    except Exception:
        return 0.0


def round_half_up_to_10(value):
    value = float(value or 0)
    if value >= 0:
        return math.floor(value / 10 + 0.5) * 10
    return math.ceil(value / 10 - 0.5) * 10


def point_round(yen):
    yen = float(yen or 0)
    if yen <= 0:
        return 0
    if yen <= 15:
        return 1
    x = yen / 10
    base = math.floor(x)
    if x - base > 0.5:
        return base + 1
    return base


def route_type(route):
    route = str(route)
    if "内用" in route or "内服" in route:
        return "内服薬"
    if "外用" in route:
        return "外用薬"
    if "注射" in route:
        return "注射薬"
    return route


def remove_long_flag_from_display(value):
    value = clean_text(value)
    value = value.replace("|長期収載品|", "").replace("｜長期収載品｜", "")
    return clean_text(value)


def is_long_term_by_code(long_code_set, code):
    code = clean_code(code)
    if not code:
        return False
    return code in long_code_set


def make_drug_display_name(name, code, long_code_set):
    name = clean_text(name)
    code = clean_code(code)
    if not name:
        return ""
    if is_long_term_by_code(long_code_set, code):
        return f"{name} |長期収載品|"
    return name


# ----------------------------------------------------------
# データ読み込み
# ----------------------------------------------------------

def load_data_a():
    files = get_files(DATA_A_DIR, "*.xlsx")
    if not files:
        raise FileNotFoundError(f"DataAのxlsxが見つかりません: {DATA_A_DIR}")

    df_list = []
    for path in files:
        raw = pd.read_excel(path, header=None, dtype=str, engine="openpyxl").fillna("")
        header_row = None
        for i in range(min(50, len(raw))):
            row_text = "".join(raw.iloc[i].astype(str).tolist())
            if "薬価基準収載医薬品コード" in row_text and "品名" in row_text and "薬価" in row_text:
                header_row = i
                break
        if header_row is None:
            continue

        df = pd.read_excel(path, header=header_row, dtype=str, engine="openpyxl").fillna("")
        if df.shape[1] < 13:
            continue

        df2 = pd.DataFrame()
        df2["区分"] = df.iloc[:, 0].map(clean_text)
        df2["薬価基準収載医薬品コード"] = df.iloc[:, 1].apply(clean_code)
        df2["規格"] = df.iloc[:, 3].map(clean_text)
        df2["品名"] = df.iloc[:, 7].map(clean_text)
        df2["薬価"] = to_number(df.iloc[:, 12])

        df2["区分"] = df2["区分"].replace("", pd.NA).ffill().fillna("")
        df2 = df2[df2["区分"].isin(["内用薬", "外用薬", "注射薬"])]
        df2 = df2[df2["品名"] != ""]
        df2 = df2[df2["薬価基準収載医薬品コード"] != ""]
        df2 = df2[df2["薬価"] > 0]
        df_list.append(df2)

    if not df_list:
        raise RuntimeError("DataAを1件も読み込めませんでした。")

    data_a = pd.concat(df_list, ignore_index=True)
    data_a = data_a.drop_duplicates(
        subset=["薬価基準収載医薬品コード", "品名", "規格"], keep="first"
    ).reset_index(drop=True)
    return data_a


def load_data_b():
    files = get_files(DATA_B_DIR, "*.xlsx")
    if not files:
        raise FileNotFoundError(f"DataBのxlsxが見つかりません: {DATA_B_DIR}")

    df_list = []
    for path in files:
        raw = pd.read_excel(path, header=None, dtype=str, engine="openpyxl").fillna("")
        header_row = None
        for i in range(min(80, len(raw))):
            row_text = "".join(raw.iloc[i].astype(str).tolist())
            if "薬価基準収載医薬品コード" in row_text and "保険外併用療養費" in row_text:
                header_row = i
                break
        if header_row is None:
            continue

        df = pd.read_excel(path, header=header_row, dtype=str, engine="openpyxl").fillna("")
        df.columns = [clean_text(c) for c in df.columns]

        code_col = price1_col = price2_col = None
        for c in df.columns:
            c_text = clean_text(c)
            if code_col is None and c_text == "薬価基準収載医薬品コード":
                code_col = c
            if price1_col is None and c_text == "保険外併用療養費の算出に用いる価格":
                price1_col = c
            if price2_col is None and c_text == "長期収載品と後発医薬品の価格差の２分の１":
                price2_col = c

        if None in (code_col, price1_col, price2_col):
            continue

        df2 = pd.DataFrame()
        df2["薬価基準収載医薬品コード"] = df[code_col].apply(clean_code)
        df2["保険外併用療養費の算出に用いる価格"] = to_number(df[price1_col])
        df2["長期収載品と後発医薬品の価格差の２分の１"] = to_number(df[price2_col])
        df2 = df2[df2["薬価基準収載医薬品コード"] != ""]
        df_list.append(df2)

    if not df_list:
        raise RuntimeError("DataBを1件も読み込めませんでした。")

    data_b = pd.concat(df_list, ignore_index=True)
    data_b = data_b.drop_duplicates(
        subset=["薬価基準収載医薬品コード"], keep="first"
    ).reset_index(drop=True)
    return data_b


def read_csv_auto(path):
    for enc in ["utf-8-sig", "cp932", "utf-8"]:
        try:
            return pd.read_csv(path, encoding=enc, dtype=str).fillna("")
        except Exception:
            pass
    raise RuntimeError(f"CSVを読み込めません: {path}")


def load_data_c():
    files = get_files(DATA_C_DIR, "*.csv")
    if not files:
        raise FileNotFoundError(f"DataCのcsvが見つかりません: {DATA_C_DIR}")

    df = read_csv_auto(files[0])
    df.columns = [clean_text(c) for c in df.columns]

    if "用法名" not in df.columns:
        for c in df.columns:
            if "用法" in str(c):
                df = df.rename(columns={c: "用法名"})
                break

    if "用法名" not in df.columns:
        raise KeyError("DataCに用法名列がありません。")

    df["用法名"] = df["用法名"].map(clean_text)
    df = df[df["用法名"] != ""]
    return df


def load_all():
    """起動時に一度だけ呼ぶ。返り値をアプリ全体で使い回す。"""
    data_a = load_data_a()
    data_b = load_data_b()
    data_c = load_data_c()
    long_code_set = set(data_b["薬価基準収載医薬品コード"].astype(str).map(clean_code))
    return data_a, data_b, data_c, long_code_set


# ----------------------------------------------------------
# 検索
# ----------------------------------------------------------

def find_drug_by_name(data_a, name):
    name = remove_long_flag_from_display(name)
    if not name:
        return None
    hit = data_a[data_a["品名"].astype(str).map(clean_text) == name]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()


def search_drug_display_names(data_a, keyword, long_code_set, limit=20):
    keyword = remove_long_flag_from_display(keyword)
    if not keyword:
        return []
    hit = data_a[data_a["品名"].astype(str).str.contains(keyword, case=False, na=False)]
    results = []
    for _, row in hit.drop_duplicates(subset=["品名"]).head(limit).iterrows():
        results.append(
            make_drug_display_name(row["品名"], row["薬価基準収載医薬品コード"], long_code_set)
        )
    return results


def search_usage_names(data_c, keyword, limit=20):
    keyword = clean_text(keyword)
    if not keyword:
        return []
    hit = data_c[data_c["用法名"].astype(str).str.contains(keyword, case=False, na=False)]
    return hit["用法名"].drop_duplicates().head(limit).tolist()


# ----------------------------------------------------------
# 計算
# ----------------------------------------------------------

def get_b_row(data_b, code):
    code = clean_code(code)
    if not code:
        return None
    hit = data_b[data_b["薬価基準収載医薬品コード"].astype(str).map(clean_code) == code]
    if hit.empty:
        return None
    return hit.iloc[0]


def calc_total(rows, data_b, long_code_set, burden_rate):
    insurance_internal = {}
    self_internal = {}
    insurance_points = 0
    self_points = 0

    for r in rows:
        drug = r.get("drug")
        if drug is None:
            continue
        qty = float(r.get("qty") or 0)
        if qty <= 0:
            continue

        code = clean_code(drug["薬価基準収載医薬品コード"])
        route = route_type(drug["区分"])
        usage = r.get("usage") or ""
        special = r.get("special") or ""
        days = int(r.get("days") or 1)

        is_long = is_long_term_by_code(long_code_set, code)
        b_row = get_b_row(data_b, code) if is_long else None

        if is_long and b_row is not None:
            insurance_price = float(b_row["保険外併用療養費の算出に用いる価格"])
            self_price = float(b_row["長期収載品と後発医薬品の価格差の２分の１"])
        else:
            insurance_price = float(drug["薬価"])
            self_price = 0.0

        insurance_yen = qty * insurance_price
        self_yen = qty * self_price

        if route == "内服薬":
            key = (usage, special, days)
            insurance_internal[key] = insurance_internal.get(key, 0) + insurance_yen
            if self_yen > 0:
                self_internal[key] = self_internal.get(key, 0) + self_yen
        else:
            insurance_points += point_round(insurance_yen)
            if self_yen > 0:
                self_points += point_round(self_yen)

    for key, yen in insurance_internal.items():
        days = key[2]
        insurance_points += point_round(yen) * days

    for key, yen in self_internal.items():
        days = key[2]
        self_points += point_round(yen) * days

    insurance_payment = round_half_up_to_10(insurance_points * 10 * burden_rate)
    self_payment = self_points * 11

    return insurance_payment + self_payment
