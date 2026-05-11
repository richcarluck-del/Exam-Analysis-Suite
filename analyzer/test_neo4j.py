from neo4j import GraphDatabase

# --- 请在这里填入您的 Neo4j 连接信息 ---
URI = "neo4j://127.0.0.1:7687"
USER = "neo4j"
PASSWORD = "exam123456"
# -------------------------------------

class Neo4jConnection:
    def __init__(self, uri, user, password):
        self.driver = None
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            print("驱动程序创建成功。")
        except Exception as e:
            print(f"创建驱动时出错: {e}")

    def close(self):
        if self.driver is not None:
            self.driver.close()
            print("驱动程序已关闭。")

    def verify_connection(self):
        if not self.driver:
            print("驱动不存在，无法验证连接。")
            return
        try:
            print("正在验证连接...")
            self.driver.verify_connectivity()
            print("\n[成功] Neo4j 连接成功！数据库已准备就绪。")
        except Exception as e:
            print(f"\n[失败] 连接验证失败: {e}")
            if "authentication" in str(e).lower():
                print("\n[提示] 错误信息包含 'authentication'，这极有可能是密码不正确。请仔细检查 PASSWORD 设置。")
            else:
                print("\n[提示] 连接失败，请检查：\n1. Neo4j 数据库服务是否正在运行。\n2. URI 地址是否正确。\n3. 防火墙是否阻止了 7687 端口的连接。")

if __name__ == "__main__":
    conn = Neo4jConnection(URI, USER, PASSWORD)
    conn.verify_connection()
    conn.close()
