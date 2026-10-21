
# Use a Python environment
FROM python:3.12-slim

# Create a working directory inside Docker
WORKDIR /app

# Install the testing tool
RUN pip install --no-cache-dir pytest

# Copy our sample files into Docker
COPY . .

# Run the tests automatically
CMD ["pytest", "-v"]
