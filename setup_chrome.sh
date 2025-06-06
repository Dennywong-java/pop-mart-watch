#!/bin/bash

# 安装 Chrome 和依赖
sudo yum update -y
sudo yum install -y chromium chromium-headless chromedriver
sudo yum install -y xorg-x11-server-Xvfb

# 验证安装
chromium --version
chromedriver --version 