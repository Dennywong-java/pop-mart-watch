#!/bin/bash

# 添加 Chrome 仓库
sudo curl -o /etc/yum.repos.d/google-chrome.repo https://dl.google.com/linux/chrome/rpm/stable/x86_64/google-chrome-stable.repo

# 安装依赖
sudo yum update -y
sudo yum install -y google-chrome-stable
sudo yum install -y xorg-x11-server-Xvfb

# 验证安装
google-chrome --version
chromedriver --version

# 设置 Chrome 二进制文件位置
echo "export CHROME_BINARY=/usr/bin/google-chrome" >> ~/.bashrc
source ~/.bashrc 