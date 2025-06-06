#!/bin/bash

# 添加 Chrome 仓库
sudo curl -o /etc/yum.repos.d/google-chrome.repo https://dl.google.com/linux/chrome/rpm/stable/x86_64/google-chrome-stable.repo

# 安装 Chrome
sudo yum install -y google-chrome-stable

# 获取 Chrome 版本
CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | awk -F. '{print $1}')

# 下载对应版本的 ChromeDriver
CHROMEDRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_137")
echo "正在下载 ChromeDriver 版本: ${CHROMEDRIVER_VERSION}"
wget -N "https://chromedriver.storage.googleapis.com/${CHROMEDRIVER_VERSION}/chromedriver_linux64.zip"
unzip -o chromedriver_linux64.zip

# 移动 ChromeDriver 到系统目录
sudo mv chromedriver /usr/local/bin/
sudo chmod +x /usr/local/bin/chromedriver

# 清理下载文件
rm -f chromedriver_linux64.zip

# 验证安装
echo "Chrome version:"
google-chrome --version
echo "ChromeDriver version:"
chromedriver --version

# 设置 Chrome 二进制文件位置
echo "export CHROME_BINARY=/usr/bin/google-chrome" >> ~/.bashrc
source ~/.bashrc 