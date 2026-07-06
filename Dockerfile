# পাইথনের অফিশিয়াল লাইটওয়েট ভার্সন
FROM python:3.10-slim

# সার্ভারে আমাদের কাজের ডিরেক্টরি সেট করা
WORKDIR /app

# curl_cffi ঠিকমতো কাজ করার জন্য প্রয়োজনীয় সিস্টেম প্যাকেজ ইনস্টল করা
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# প্রথমে requirements.txt কপি করা (যাতে ক্যাশ ঠিকমতো কাজ করে)
COPY requirements.txt .

# পাইথনের প্যাকেজগুলো ইনস্টল করা
RUN pip install --no-cache-dir -r requirements.txt

# এবার আপনার main.py সহ বাকি কোড কপি করা
COPY . .

# Koyeb এর জন্য পোর্ট 8000 ওপেন রাখা
EXPOSE 8000

# API চালু করার ফাইনাল কমান্ড
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
