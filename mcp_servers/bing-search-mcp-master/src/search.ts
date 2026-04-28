import { chromium, devices, BrowserContextOptions, Browser, Response } from "playwright";
import { SearchResponse, SearchResult, CommandOptions } from "./types.js";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import logger from "./logger.js";

// 指纹配置接口
interface FingerprintConfig {
  deviceName: string;
  locale: string;
  timezoneId: string;
  colorScheme: "dark" | "light";
  reducedMotion: "reduce" | "no-preference";
  forcedColors: "active" | "none";
}

// 保存的状态文件接口
interface SavedState {
  fingerprint?: FingerprintConfig;
  bingDomain?: string;
}

/**
 * 获取宿主机器的实际配置
 * @param userLocale 用户指定的区域设置（如果有）
 * @returns 基于宿主机器的指纹配置
 */
function getHostMachineConfig(userLocale?: string): FingerprintConfig {
  // 获取系统区域设置
  const systemLocale = userLocale || process.env.LANG || "zh-CN";

  // 获取系统时区
  const timezoneOffset = new Date().getTimezoneOffset();
  let timezoneId = "Asia/Shanghai";

  if (timezoneOffset <= -480 && timezoneOffset > -600) {
    timezoneId = "Asia/Shanghai";
  } else if (timezoneOffset <= -540) {
    timezoneId = "Asia/Tokyo";
  } else if (timezoneOffset <= -420 && timezoneOffset > -480) {
    timezoneId = "Asia/Bangkok";
  } else if (timezoneOffset <= 0 && timezoneOffset > -60) {
    timezoneId = "Europe/London";
  } else if (timezoneOffset <= 60 && timezoneOffset > 0) {
    timezoneId = "Europe/Berlin";
  } else if (timezoneOffset <= 300 && timezoneOffset > 240) {
    timezoneId = "America/New_York";
  }

  const hour = new Date().getHours();
  const colorScheme =
    hour >= 19 || hour < 7 ? ("dark" as const) : ("light" as const);

  const reducedMotion = "no-preference" as const;
  const forcedColors = "none" as const;
  const deviceName = "Desktop Chrome";

  return {
    deviceName,
    locale: systemLocale,
    timezoneId,
    colorScheme,
    reducedMotion,
    forcedColors,
  };
}

/**
 * 执行Bing搜索并返回结果
 * @param query 搜索关键词
 * @param options 搜索选项
 * @returns 搜索结果
 */
export async function bingSearch(
  query: string,
  options: CommandOptions = {},
  existingBrowser?: Browser
): Promise<SearchResponse> {
  const {
    limit = 10,
    timeout = 60000,
    stateFile = path.join(os.homedir(), ".bing-search-browser-state.json"),
    noSaveState = false,
    locale = "zh-CN",
    region = "cn",
  } = options;

  const stateFilePath = path.resolve(stateFile);
  const fingerprintFilePath = stateFilePath.replace(".json", "-fingerprint.json");

  let savedState: SavedState = {};
  let fingerprint: FingerprintConfig = getHostMachineConfig(locale);

  try {
    if (fs.existsSync(fingerprintFilePath)) {
      const fingerprintData = fs.readFileSync(fingerprintFilePath, "utf-8");
      fingerprint = JSON.parse(fingerprintData);
      logger.info("已加载浏览器指纹配置");
    } else {
      fs.writeFileSync(
        fingerprintFilePath,
        JSON.stringify(fingerprint, null, 2)
      );
      logger.info("已生成并保存新的浏览器指纹配置");
    }
  } catch (error) {
    logger.warn("加载或保存浏览器指纹配置时出错，使用默认配置");
  }

  try {
    if (fs.existsSync(stateFilePath)) {
      const stateData = fs.readFileSync(stateFilePath, "utf-8");
      savedState = JSON.parse(stateData);
      logger.info("已加载保存的状态");
    }
  } catch (error) {
    logger.warn("加载保存的状态时出错，将使用新会话");
  }

  const useHeadless = false;

  logger.info({ options }, "正在初始化浏览器...");

  let storageState: string | undefined = undefined;

  if (fs.existsSync(stateFilePath)) {
    logger.info({ stateFile }, "发现浏览器状态文件，将使用保存的浏览器状态");
    storageState = stateFilePath;
  } else {
    logger.info({ stateFile }, "未找到浏览器状态文件，将创建新的浏览器会话");
  }

  const getRandomDelay = (min: number, max: number) => {
    return Math.floor(Math.random() * (max - min + 1)) + min;
  };

  async function performSearch(headless: boolean): Promise<SearchResponse> {
    let browser: Browser;
    let browserWasProvided = false;

    if (existingBrowser) {
      browser = existingBrowser;
      browserWasProvided = true;
      logger.info("使用已存在的浏览器实例");
    } else {
      logger.info({ headless }, `准备以${headless ? "无头" : "有头"}模式启动浏览器...`);

      browser = await chromium.launch({
        headless,
        timeout: timeout * 2,
        args: [
          "--disable-blink-features=AutomationControlled",
          "--disable-features=IsolateOrigins,site-per-process",
          "--disable-site-isolation-trials",
          "--disable-web-security",
          "--no-sandbox",
          "--disable-setuid-sandbox",
          "--disable-dev-shm-usage",
          "--disable-accelerated-2d-canvas",
          "--no-first-run",
          "--no-zygote",
          "--disable-gpu",
          "--hide-scrollbars",
          "--mute-audio",
          "--disable-background-networking",
          "--disable-background-timer-throttling",
          "--disable-backgrounding-occluded-windows",
          "--disable-breakpad",
          "--disable-component-extensions-with-background-pages",
          "--disable-extensions",
          "--disable-features=TranslateUI",
          "--disable-ipc-flooding-protection",
          "--disable-renderer-backgrounding",
          "--enable-features=NetworkService,NetworkServiceInProcess",
          "--force-color-profile=srgb",
          "--metrics-recording-only",
        ],
        ignoreDefaultArgs: ["--enable-automation"],
      });

      logger.info("浏览器已成功启动!");
    }

    const deviceConfig = devices["Desktop Chrome"];
    let contextOptions: BrowserContextOptions = { ...deviceConfig };

    if (savedState.fingerprint) {
      contextOptions = {
        ...contextOptions,
        locale: savedState.fingerprint.locale,
        timezoneId: savedState.fingerprint.timezoneId,
        colorScheme: savedState.fingerprint.colorScheme,
        reducedMotion: savedState.fingerprint.reducedMotion,
        forcedColors: savedState.fingerprint.forcedColors,
      };
      logger.info("使用保存的浏览器指纹配置");
    } else {
      const hostConfig = getHostMachineConfig(locale);
      contextOptions = {
        ...contextOptions,
        locale: hostConfig.locale,
        timezoneId: hostConfig.timezoneId,
        colorScheme: hostConfig.colorScheme,
        reducedMotion: hostConfig.reducedMotion,
        forcedColors: hostConfig.forcedColors,
      };
      savedState.fingerprint = hostConfig;
      logger.info("已根据宿主机器生成新的浏览器指纹配置");
    }

    contextOptions = {
      ...contextOptions,
      permissions: ["geolocation", "notifications"],
      acceptDownloads: true,
      isMobile: false,
      hasTouch: false,
      javaScriptEnabled: true,
    };

    const context = await browser.newContext(
      storageState ? { ...contextOptions, storageState } : contextOptions
    );

    await context.addInitScript(() => {
      Object.defineProperty(navigator, "webdriver", { get: () => false });
      Object.defineProperty(navigator, "plugins", { get: () => [1, 2, 3, 4, 5] });
      Object.defineProperty(navigator, "languages", { get: () => ["en-US", "en", "zh-CN"] });
      // @ts-ignore
      window.chrome = { runtime: {}, loadTimes: function () {}, csi: function () {}, app: {} };
    });

    const page = await context.newPage();

    await page.addInitScript(() => {
      Object.defineProperty(window.screen, "width", { get: () => 1920 });
      Object.defineProperty(window.screen, "height", { get: () => 1080 });
      Object.defineProperty(window.screen, "colorDepth", { get: () => 24 });
      Object.defineProperty(window.screen, "pixelDepth", { get: () => 24 });
    });

    try {
      logger.info("正在访问Bing搜索页面...");
      const selectedDomain = "www.bing.com";
      savedState.bingDomain = selectedDomain;

      const searchUrl = `https://${selectedDomain}/search?q=${encodeURIComponent(query)}`;
      logger.info({ url: searchUrl, query, locale }, "正在访问Bing搜索页面");

      let response: Response | null = null;
      let retryCount = 0;
      const maxRetries = 3;
      let manualVerificationPassed = false;

      while (retryCount < maxRetries) {
        try {
          response = await page.goto(searchUrl, {
            timeout: timeout * 2,
            waitUntil: "domcontentloaded",
          });

          if (response && response.ok()) {
            logger.info("页面加载成功");
            break;
          }
          throw new Error(`页面加载状态码: ${response?.status()}`);
        } catch (error) {
          logger.error({ error: error instanceof Error ? error.message : String(error), retry: retryCount + 1 }, "页面加载出错");
          
          if (!headless) {
             logger.warn("检测到有头模式，等待人工修复网络或验证码问题...");
             const maxWaitTime = 300000;
             const checkInterval = 2000;
             let waitedTime = 0;
             
             while (waitedTime < maxWaitTime) {
               await page.waitForTimeout(checkInterval);
               waitedTime += checkInterval;
               
               // 检查是否已成功加载（简单的判断：标题包含搜索词或Bing）
               const title = await page.title();
               if (title.includes("Bing") || title.includes(query)) {
                 logger.info("检测到页面已恢复，继续执行...");
                 manualVerificationPassed = true;
                 break;
               }
             }
             if (manualVerificationPassed) break;
          } else {
             await page.waitForTimeout(2000);
          }
          retryCount++;
        }
      }

      if (!manualVerificationPassed && retryCount >= maxRetries && (!response || !response.ok())) {
        throw new Error(`无法加载Bing搜索页面，已重试${maxRetries}次`);
      }

      // 检查是否被重定向到验证页面 (Bing 的验证页面特征可能不同，这里作为通用处理)
      const currentUrl = page.url();
      if (currentUrl.includes("challenge") || (await page.title()).includes("Challenge")) {
         logger.warn("检测到可能的验证页面");
         if (!headless) {
             const maxWaitTime = 300000;
             const checkInterval = 2000;
             let waitedTime = 0;
             while (waitedTime < maxWaitTime) {
                 await page.waitForTimeout(checkInterval);
                 waitedTime += checkInterval;
                 const title = await page.title();
                 if (!title.includes("Challenge") && (title.includes("Bing") || title.includes(query))) {
                     logger.info("验证通过");
                     break;
                 }
             }
         }
      }

      const isSearchResultPage = currentUrl.includes("/search") && currentUrl.includes("q=");
      if (isSearchResultPage) {
        logger.info("已经在搜索结果页面");
      } else {
         // 如果不是直接通过URL访问到结果页（极少情况），尝试输入
         // Bing 搜索框通常是 input[name='q']
         const searchInput = await page.$("input[name='q'], textarea[name='q'], #sb_form_q");
         if (searchInput) {
             await searchInput.fill(query);
             await page.keyboard.press("Enter");
             await page.waitForLoadState("domcontentloaded");
         }
      }

      logger.info("正在等待搜索结果加载...");
      // Bing 结果容器通常是 #b_results > .b_algo
      try {
        await page.waitForSelector("#b_results", { timeout });
      } catch (e) {
        logger.warn("等待结果容器超时，尝试直接提取");
      }

      logger.info("正在提取搜索结果...");
      const results = await page.$$eval(
        "#b_results > li.b_algo",
        (elements, maxResults) => {
          return elements
            .slice(0, maxResults)
            .map((el) => {
              const titleElement = el.querySelector("h2 a");
              const linkElement = el.querySelector("h2 a");
              const snippetElement = el.querySelector(".b_caption p, .b_snippet, .b_lineclamp3"); // 尝试多种摘要选择器

              return {
                title: titleElement ? titleElement.textContent || "" : "",
                link: linkElement && linkElement instanceof HTMLAnchorElement ? linkElement.href : "",
                snippet: snippetElement ? snippetElement.textContent || "" : "",
              };
            })
            .filter((item) => item.title && item.link);
        },
        limit
      );

      logger.info({ count: results.length }, "提取到的结果数量");

      if (!noSaveState) {
        try {
            const stateDir = path.dirname(stateFilePath);
            if (!fs.existsSync(stateDir)) fs.mkdirSync(stateDir, { recursive: true });
            await context.storageState({ path: stateFilePath });
            fs.writeFileSync(fingerprintFilePath, JSON.stringify(savedState, null, 2));
        } catch (e) {
            logger.error({ error: e instanceof Error ? e.message : String(e) }, "保存状态失败");
        }
      }

      if (!browserWasProvided) {
        await browser.close();
      }

      return {
        query,
        results,
        language: locale,
        region,
      };

    } catch (error) {
      logger.error({ error: error instanceof Error ? error.message : String(error) }, "搜索错误");
      if (!browserWasProvided && browser) {
        await browser.close();
      }
      return {
        query,
        results: [{ title: "搜索失败", link: "", snippet: `错误: ${error instanceof Error ? error.message : String(error)}` }],
        language: locale,
        region,
      };
    }
  }

  return performSearch(useHeadless);
}