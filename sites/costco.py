from selenium import webdriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as wait
from webdriver_manager.chrome import ChromeDriverManager
from chromedriver_py import binary_path as driver_path
from utils import random_delay, send_webhook, create_msg
import settings, time

class Costco:
    def __init__(self, task_id, status_signal, image_signal, product, profile, proxy, monitor_delay, error_delay, max_price):
        self.task_id, self.status_signal, self.image_signal, self.product, self.profile, self.monitor_delay, self.error_delay, self.max_price = task_id, status_signal, image_signal, product, profile, float(
            monitor_delay), float(error_delay), max_price

        starting_msg = "Starting Costco"
        self.browser = self.init_driver()
        self.product_image = None

        if proxy:
            self.session.proxies.update(proxy)

        self.SHORT_TIMEOUT = 5
        self.LONG_TIMEOUT = 20

        if settings.dont_buy:
            starting_msg = "Starting Costco in dev mode; will not actually checkout."

        self.status_signal.emit(create_msg(starting_msg, "normal"))
        self.login()
        self.load_product()
        self.monitor()
        self.load_checkout()
        self.check_out()

    def init_driver(self):
        driver_manager = ChromeDriverManager()
        driver_manager.install()
        var = driver_path
        browser = webdriver.Chrome(driver_path)

        browser.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                  Object.defineProperty(navigator, 'webdriver', {
                   get: () => undefined
                  })
                """
        })

        return browser

    def login(self):
        self.status_signal.emit(create_msg("Logging In", "normal"))
        authenticated = False
        while not authenticated:
            try:
                self.browser.get("https://www.costco.com/LogonForm")
                wait(self.browser, self.LONG_TIMEOUT).until(EC.presence_of_element_located((By.ID, "logonId"))).send_keys(settings.costco_user)
                wait(self.browser, self.LONG_TIMEOUT).until(EC.presence_of_element_located((By.ID, "logonPassword"))).send_keys(settings.costco_pass)
                time.sleep(1)
                wait(self.browser, self.LONG_TIMEOUT).until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[value="Sign In"]')))
                self.browser.find_element_by_css_selector('[value="Sign In"]').click()
                wait(self.browser, self.LONG_TIMEOUT).until(EC.presence_of_element_located((By.ID, "myaccount-d")))
                authenticated = True
            except:
                time.sleep(self.SHORT_TIMEOUT)

    def load_product(self):
        product_loaded = False
        while not product_loaded:
            try:
                self.status_signal.emit(create_msg("Loading Product", "normal"))
                self.browser.get(self.product)
                wait(self.browser, self.LONG_TIMEOUT).until(lambda _: self.browser.current_url == self.product)
                product_loaded = True
            except:
                time.sleep(self.SHORT_TIMEOUT)

    def monitor(self):
        in_stock = False
        while not in_stock:
            try:
                wait(self.browser, random_delay(self.monitor_delay, settings.random_delay_start, settings.random_delay_stop)).until(EC.element_to_be_clickable((By.ID, "add-to-cart-btn")))
                self.status_signal.emit(create_msg("In Stock", "normal"))
                in_stock = True
                in_cart = False
                while not in_cart:
                    self.browser.find_element_by_css_selector('#add-to-cart-btn').click()
                    time.sleep(1)
                    try:
                        wait(self.browser, self.LONG_TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".added-to-cart")))
                        in_cart = True
                        self.status_signal.emit(create_msg("Added to cart", "normal"))
                    except:
                        time.sleep(self.SHORT_TIMEOUT)
            except:
                in_stock = False
                time.sleep(self.SHORT_TIMEOUT)
                self.status_signal.emit(create_msg("Waiting For Restock", "normal"))
                self.browser.refresh()

    def load_checkout(self):
        self.status_signal.emit(create_msg("Checking Out", "normal"))
        checkout_loaded = False
        while not checkout_loaded:
            try:
                self.browser.get("https://www.costco.com/SinglePageCheckoutView")
                wait(self.browser, self.LONG_TIMEOUT).until(lambda _: self.browser.current_url == "https://www.costco.com/SinglePageCheckoutView")
                checkout_loaded = True
            except:
                time.sleep(self.SHORT_TIMEOUT)

    def check_out(self):
        ordered = False
        while not ordered:
            try:
                self.submit_order()
                ordered = True
            except:
                try:
                    wait(self.browser, self.LONG_TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#cc_cvv_div iframe"))).send_keys(self.profile["card_cvv"])
                    time.sleep(1)
                    wait(self.browser, self.LONG_TIMEOUT).until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[value="Continue to Shipping Options"]')))
                    self.browser.find_element_by_css_selector('[value="Continue to Shipping Options"]').click()
                    self.submit_order()
                    ordered = True
                except:
                    time.sleep(self.SHORT_TIMEOUT)
                    self.browser.refresh()

    def submit_order(self):
        wait(self.browser, random_delay(self.monitor_delay, settings.random_delay_start, settings.random_delay_stop)).until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[value="Place Order"]')))
        if not settings.dont_buy:
            self.browser.find_element_by_css_selector('[value="Place Order"]').click()
            self.status_signal.emit(create_msg("Order Placed", "success"))
        else:
            self.status_signal.emit(create_msg("Mock Order Placed", "success"))
