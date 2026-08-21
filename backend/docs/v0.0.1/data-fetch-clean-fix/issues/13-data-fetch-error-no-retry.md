# P2-02: DataFetchError 不进入重试逻辑

**Type:** task  
**Status:** ready-for-agent  
**Priority:** P2

## Problem

`fetcher.py:123-130` `except DataFetchError: raise` 立即上抛，某些可重试的 DataFetchError 被跳过重试机会。

## Solution

区分可重试与不可重试的 DataFetchError 子类，或让所有 DataFetchError 进入统一重试循环。

## Files

- `backend/quant/data/fetcher.py`

## Verification

网络超时等临时错误触发重试
