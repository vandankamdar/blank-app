import streamlit as st
from nsepython import nse_optionchain_scrapper
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date
import pandas as pd
import time
import re
import os
import chromedriver_autoinstaller


SYMBOL_FILE = "symbols.txt"
driver_path = ChromeDriverManager().install()
# Set the page configuration to wide mode
st.set_page_config(layout="wide")

# ------------------------------- Fetch & Clean Symbols -------------------------------
def scrape_symbols():
    chromedriver_autoinstaller.install()

    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(options=options)

    try:
        driver.get("https://zerodha.com/margin-calculator/SPAN/")
        dropdown = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "select2-selection--single"))
        )
        dropdown.click()

        options_list = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".select2-results__options li"))
        )

        symbols = [opt.text for opt in options_list if opt.text.strip() != '']

        # Save to file
        with open(SYMBOL_FILE, "w") as f:
            for symbol in symbols:
                f.write(symbol + "\n")

        return symbols

    finally:
        driver.quit()

# ------------------------------- Load from File -------------------------------
def load_symbols_from_file():
    if os.path.exists(SYMBOL_FILE):
        with open(SYMBOL_FILE, "r") as f:
            return sorted(set([line.strip() for line in f if line.strip()]))
    return []

# ------------------------------- STEP 2: Margin Calculator Logic -------------------------------
def get_last_expiry_date():
    today = date.today()
    first_day_next_month = date(today.year, today.month + 1, 1) if today.month != 12 else date(today.year + 1, 1, 1)
    last_day = first_day_next_month - timedelta(days=1)
    while last_day.weekday() != 3:  # 3 = Thursday
        last_day -= timedelta(days=1)
    return last_day.strftime("%d-%b-%Y")

def select_option_span_margin(symbol, strike, opttype, product, trade):
    # Custom headers
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
                 "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    chrome_options = Options()
    chrome_options.add_argument(f"user-agent={user_agent}")
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(service=Service(driver_path), options=chrome_options)
    
    def add_option_leg(symbol, strike, opttype, product, trade):
        # 1. Product: Options
        product_dropdown = Select(driver.find_element(By.ID, "product"))
        product_dropdown.select_by_visible_text(product)

        # 2. Option Type: Puts or Calls
        option_type_dropdown = Select(driver.find_element(By.ID, "option_type"))
        option_type_dropdown.select_by_visible_text(opttype)

        # 3. Strike Price
        strike_input = driver.find_element(By.ID, "strike_price")
        strike_input.clear()
        strike_input.send_keys(strike)

        # 4. Select script (symbol)
        dropdown = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "select2-selection--single"))
        )
        dropdown.click()

        search_input = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CLASS_NAME, "select2-search__field"))
        )
        search_input.send_keys(symbol)
        time.sleep(1.5)
        search_input.send_keys(Keys.DOWN)
        search_input.send_keys(Keys.ENTER)

        # 4b. Get lot size
        lot_size_elem = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#lot_size .val"))
            )
        lot_size = lot_size_elem.text.strip()
        
        # Wait for dropdown to disappear
        WebDriverWait(driver, 5).until(
            EC.invisibility_of_element_located((By.CLASS_NAME, "select2-results"))
        )

        # 5. Buy/Sell radio
        radio_xpath = f'//input[@name="trade[]" and @value="{trade}"]'
        radio_button = driver.find_element(By.XPATH, radio_xpath)
        driver.execute_script("arguments[0].click();", radio_button)
##        print(f"✅ Added leg: {trade.upper()} {symbol} {strike} {opttype}")

        # 6. Click Add
        add_button = driver.find_element(By.CSS_SELECTOR, 'input[type="submit"][value="Add"]')
        add_button.click()
##        print("✅ Clicked 'Add' button.")
        time.sleep(2)

        return lot_size

    try:
        driver.get("https://zerodha.com/margin-calculator/SPAN/")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "product")))
        time.sleep(2)
        # ➕ First leg: Sell RELIANCE 1490 PE
        lot_size = add_option_leg(symbol, strike, opttype, product, trade)

        # ➕ Second leg: Buy RELIANCE 1460 PE
        # add_option_leg(symbol="RELIANCE", strike="1450", opttype="Puts", product="Options", trade="buy")

        # ✅ Extract margin values
        span = driver.find_element(By.CSS_SELECTOR, "#tally .val.span").text
        exposure = driver.find_element(By.CSS_SELECTOR, "#tally .val.exposure").text
        premium = driver.find_element(By.CSS_SELECTOR, "#tally .netoptionvalue .val").text
        total_margin = driver.find_element(By.CSS_SELECTOR, "#tally .val.total").text
##        st.error(f"Strike : {strike}, Margin : {total_margin}, Lot Size : {lot_size}")
        return total_margin,lot_size
##        print("\n🔍 Combined Margin Details:")
##        print(f"📦 SPAN Margin          : {span}")
##        print(f"📦 Exposure Margin      : {exposure}")
##        print(f"💰 Premium Receivable   : {premium}")
##        print(f"🧮 Total Margin Required: {total_margin}")

    except Exception as e:
        st.error(f"❌ Error: {e}")
        driver.save_screenshot("error_debug.png")
        return None
    finally:
        print("✅ Done.")
        driver.quit()
        

# ------------------------------- STEP 3: Option Chain Processor -------------------------------
def process_option_chain(scrip):
    cleaned_symbol = re.sub(r'\s*\(.*?\)|\s+\d{1,2}-[A-Za-z]{3}-\d{4}', '', scrip)
    try:
        data = nse_optionchain_scrapper(cleaned_symbol)
    except Exception as e:
        st.error(f"Error fetching option chain: {e}")
        return pd.DataFrame()

    expiry = get_last_expiry_date()
    records = data['records']['data']
    pe_data = []

    def process_record(record):
        pe = record.get("PE")
        if pe and pe["expiryDate"] == expiry and pe['strikePrice'] < pe["underlyingValue"]:
            symbol_with_expiry = f"{scrip} {expiry}"
            try:
                margin_details = select_option_span_margin(scrip, pe["strikePrice"], "Puts", "Options", "sell")
                if not margin_details:
                    return None
                margin = float(margin_details[0].replace("Rs.", "").replace(",", "").strip())
                lot_size = int(margin_details[1].strip())
                premium = lot_size * pe["lastPrice"]
                
                return {
                    "scrip": scrip,
                    "lotSize": lot_size,
                    "strikePrice": pe["strikePrice"],
                    "% Var": round(((pe["strikePrice"] - data["records"]["underlyingValue"]) / data["records"]["underlyingValue"]) * 100, 2),
                    "expiryDate": pe["expiryDate"],
                    "openInterest": pe["openInterest"],
                    "changeInOI": pe["changeinOpenInterest"],
                    "lastPrice": pe["lastPrice"],
                    "impliedVolatility": pe["impliedVolatility"],
                    "underlyingValue": data["records"]["underlyingValue"],
                    "margin": margin,
                    "premium": premium,
                    "ROI (%)": round((premium / margin) * 100, 2) if margin > 0 else 0,
                    "premium/share": pe["lastPrice"]
                }
            except Exception as e:
                error_msg = f"⚠️ Error processing {pe['strikePrice']}: {e}"
                st.error(error_msg)
        return None
    # Run with multithreading
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_record, record) for record in records]

        for future in as_completed(futures):
            result = future.result()
            if result:
                pe_data.append(result)
##    for record in records:
##        result = process_record(record)
##        if result:
##            pe_data.append(result)
    df = pd.DataFrame(sorted(pe_data, key=lambda x: x["strikePrice"]))
    return df


# ------------------------------- STEP 4: Streamlit App UI -------------------------------

symbols = load_symbols_from_file()
if not symbols:
    st.warning("⚠ No symbols found. Please click 'Refresh Symbol List' to load.")
# ------------------------------- Dropdown + Refresh Button -------------------------------
# ------------------------------- Dropdown + Refresh Button -------------------------------
col1, col2 = st.columns([5, 1])

with col1:
    if symbols:
        symbols_with_blank = [""] + symbols
        selected_symbol = st.selectbox("Select a symbol:", symbols_with_blank, key="symbol_select")
    else:
        selected_symbol = None

with col2:
    # Add padding to align vertically with selectbox
    st.markdown("<div style='padding-top: 32px;'>", unsafe_allow_html=True)
    if st.button("🔁 Refresh"):
        with st.spinner("Fetching symbols from Zerodha..."):
            symbols = scrape_symbols()
        st.success(f"✅ Loaded {len(symbols)} symbols from Zerodha.")
        st.experimental_rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ------------------------------- Validatinexonon -------------------------------
if selected_symbol:
    st.success(f"You selected: {selected_symbol}")
    if st.button("Analyze"):
        with st.spinner("Fetching option chain and calculating margins..."):
            df = process_option_chain(selected_symbol)
            if df.empty:
                st.warning("No data found or failed to fetch margin data.")
            else:
    ##            st.success(f"Analysis complete!{df_result}")
                st.dataframe(df, height=1000)

elif symbols:
    st.info("ℹ Please select a symbol from the dropdown.")
else:
    st.error("❌ No symbols available. Please refresh the list.")


