from selenium import webdriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait as wait
from webdriver_manager.chrome import ChromeDriverManager
from chromedriver_py import binary_path as driver_path
from utils import random_delay, send_webhook, create_msg
from utils.selenium_utils import change_driver
import settings, time

TIMEOUT_SHORT = 5
TIMEOUT_LONG = 20
RESTART_COUNT = 100

class Costco:
    def __init__(self, task_id, status_signal, image_signal, product, profile, proxy, monitor_delay, error_delay, max_price):
        self.task_id, self.status_signal, self.image_signal, self.product, self.profile, self.monitor_delay, self.error_delay = task_id, status_signal, image_signal, product, profile, float(
            monitor_delay), float(error_delay)
        done = False
        while not done:
            try:
                self.go()
                done = True
            except:
                try:
                    self.stop()
                except:
                    None
                self.status_signal.emit(create_msg("Restarting Browser", "normal"))
                time.sleep(5)

    def go(self):
        self.sequence = [
            {'type': 'method', 'selector': '[value="Add to Cart"]', 'method': self.find_and_click_atc, 'message': 'Added to cart', 'message_type': 'normal'}
            , {'type': 'button', 'selector': '[href="/CheckoutCartView"][tabindex="-1"]', 'message': 'Viewing Cart before Checkout', 'message_type': 'normal'}
            , {'type': 'button', 'selector': '#shopCartCheckoutSubmitButton', 'message': 'Checking out', 'message_type': 'normal'}
            , {'type': 'method', 'selector': '[value="Place Order"]', 'method': self.submit_order, 'message': 'Submitting order', 'message_type': 'normal'}
        ]
        self.possible_interruptions = [
            {'type': 'input', 'selector': '#cc_cvv_div iframe', 'args': {'value': self.profile['card_cvv']}, 'message': 'Entering CVV', 'message_type': 'normal'}
            , {'type': 'button', 'selector': '[value="Continue to Shipping Options"]', 'message': 'Continue to Shipping Options', 'message_type': 'normal'}
        ]
        starting_msg = "Starting Costco"
        self.browser = self.init_driver()
        self.product_image = None
        self.did_submit = False
        self.failed = False
        self.retry_attempts = 10
        if settings.dont_buy:
            starting_msg = "Starting Costco in dev mode; will not actually checkout"
        self.status_signal.emit(create_msg(starting_msg, "normal"))
        self.status_signal.emit(create_msg("Logging In..", "normal"))
        self.login()
        self.img_found = False
        self.product_loop()
        send_webhook("OP", "Costco", self.profile["profile_name"], self.task_id, self.product_image)
    
    def init_driver(self):
        driver_manager = ChromeDriverManager()
        driver_manager.install()
        change_driver(self.status_signal, driver_path)
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
        self.browser.get("https://www.costco.com/LogonForm")
        wait(self.browser, TIMEOUT_LONG).until(EC.presence_of_element_located((By.ID, "logonId"))).send_keys(settings.costco_user)
        self.browser.find_element_by_id("logonPassword").send_keys(settings.costco_pass)
        self.browser.find_element_by_css_selector('[value="Sign In"]').click()

        # Gives it time for the login to complete
        time.sleep(random_delay(self.monitor_delay, settings.random_delay_start, settings.random_delay_stop))

    def product_loop(self):
        while not self.did_submit and not self.failed:
            self.monitor()
            self.atc_and_checkout()

    def check_stock(self, new_tab=False):
        stock = False
        if new_tab:
            windows_before = self.browser.window_handles
            self.browser.execute_script(f'window.open("{self.product}")')
            wait(self.browser, 10).until(EC.number_of_windows_to_be(2))
            new_window = [x for x in self.browser.window_handles if x not in windows_before][0]
            self.browser.switch_to_window(new_window)
        if len(self.browser.find_elements_by_css_selector('[value="Add to Cart"]')) > 0:
            stock = True
        if new_tab:
            self.browser.close()
            wait(self.browser, 10).until(EC.number_of_windows_to_be(1))
            old_window = self.browser.window_handles[0]
            self.browser.switch_to_window(old_window)
            return False
        return stock

    def monitor(self):
        self.in_stock = False
        self.browser.get(self.product)
        wait(self.browser, TIMEOUT_LONG).until(lambda _: self.browser.current_url == self.product)

        while not self.img_found:
            try:
                if not self.img_found:
                    product_img = self.browser.find_element_by_css_selector('[property="og:image"')
                    self.image_signal.emit(product_img.get_attribute("content"))
                    self.product_image = product_img.get_attribute("content")
                    self.img_found = True
            except Exception as e:
                continue

        count = 0
        while not self.in_stock:
            self.in_stock = self.check_stock()
            if self.in_stock:
                continue
            else:
                count += 1
                if count > RESTART_COUNT:
                    # raise
                    count = 0
                    self.new_tab()
                self.status_signal.emit(create_msg("Waiting on Restock", "normal"))
                time.sleep(random_delay(self.monitor_delay, settings.random_delay_start, settings.random_delay_stop))
                self.browser.refresh()

    def atc_and_checkout(self):
        while not self.did_submit:
            for step in self.sequence:
                for attempt in range(self.retry_attempts + 1):
                    try:
                        wait(self.browser, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, step['selector'])))
                        self.process_step(step)
                        break
                    except:
                        if attempt == self.retry_attempts:
                            if not self.check_stock(new_tab=True):
                                self.status_signal.emit(create_msg('Product is out of stock. Resuming monitoring.', 'error'))
                                return
                            else:
                                self.status_signal.emit(create_msg('Encountered unknown page while product in stock. Quitting.', 'error'))
                                self.failed = True
                                return
                        self.process_interruptions(attempt=attempt)

    def submit_order(self):
        self.did_submit = False
        url = self.browser.current_url
        while not self.did_submit:
            try:
                self.process_interruptions(silent=True)
                if not settings.dont_buy:
                    self.browser.find_element_by_css_selector('[value="Place Order"]').click()
                    time.sleep(5)
                    if self.browser.find_element_by_css_selector("body").get_text().contains("Order Confirmation number"):
                        self.status_signal.emit(create_msg("Order Placed", "success"))
                else:
                    self.status_signal.emit(create_msg("Mock Order Placed", "success"))
                self.save_screenshot("order")
                send_webhook("OP", "Costco", self.profile["profile_name"], self.task_id, self.product_image)
                self.did_submit = True
            except:
                self.status_signal.emit(create_msg('Retrying submit order until success', 'normal'))

    def find_and_click(self, selector):
        self.browser.find_element_by_css_selector(selector).click()
        
    def find_and_click_atc(self):
        if self.browser.current_url == self.product and self.check_stock():
            if self.browser.find_elements_by_css_selector('#add-to-cart-btn'):
                button = self.browser.find_element_by_css_selector('#add-to-cart-btn')
            else:
                button = None
        if button:
            self.atc_clicked = True
            button.click()

    def fill_field_and_proceed(self, selector, args):
        input_field = self.browser.find_element_by_css_selector(selector)
        clear = Keys.BACKSPACE * 10
        input_field.send_keys(clear + args['value'])
        if 'confirm_button' in args:
            if self.browser.find_elements_by_css_selector(args['confirm_button']):
                self.find_and_click(args['confirm_button'])

    def process_step(self, step, wait_after=False, silent=False):
        elements = self.browser.find_elements_by_css_selector(step['selector'])
        if len(elements) > 0 and elements[0].is_displayed():
            if not silent:
                self.status_signal.emit(create_msg(step['message'], step['message_type']))
            if step['type'] == 'button':
                self.find_and_click(step['selector'])
            elif step['type'] == 'method':
                step['method']()
            elif step['type'] == 'input':
                self.fill_field_and_proceed(step['selector'], step['args'])
            if wait_after:
                time.sleep(TIMEOUT_SHORT)
        
    def process_interruptions(self, attempt=0, silent=False):
        if not silent:
            self.status_signal.emit(create_msg(f'Interrupted, attempting to resolve ({attempt+1}/{self.retry_attempts})', 'error'))
            self.save_screenshot("interruption")
        for step in self.possible_interruptions:
            self.process_step(step, wait_after=True, silent=True)

    def stop(self):
        self.browser.close()
        self.browser.quit()

    def save_screenshot(self, name):
        self.browser.get_screenshot_as_file(name + time.strftime("%s") + ".png")

    def new_tab(self):
        self.status_signal.emit(create_msg("Creating new tab", "normal"))
        windows_before = self.browser.window_handles
        self.browser.execute_script(f'window.open("{self.product}")')
        wait(self.browser, 10).until(EC.number_of_windows_to_be(2))
        new_window = [x for x in self.browser.window_handles if x not in windows_before][0]
        self.browser.close()
        wait(self.browser, 10).until(EC.number_of_windows_to_be(1))
        self.browser.switch_to_window(new_window)
