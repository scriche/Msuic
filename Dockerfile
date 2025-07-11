# Use an official Python runtime as a parent image
FROM python:3.13.5-slim

# Upgrade system packages to address vulnerabilities
RUN apt-get update && apt-get upgrade -y && apt-get clean

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir discord asyncio yt-dlp pynacl

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg


# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DISCORD_TOKEN=YOUR_DISCORD_TOKEN

# Run the Python script when the container launches
CMD ["python", "-u", "msuicbot.py"]
