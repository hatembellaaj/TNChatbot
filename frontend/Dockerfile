FROM node:20-alpine

WORKDIR /app

COPY package.json ./
COPY tsconfig.json ./
COPY next-env.d.ts ./
COPY app ./app

RUN npm install

EXPOSE 3000

CMD ["npm", "run", "dev"]
