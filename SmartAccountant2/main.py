import streamlit as st
import os
import sqlite3
import xmlrpc.client
from datetime import datetime
from dotenv import load_dotenv

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.tools import Tool
from langchain import hub
import nest_asyncio

load_dotenv()
nest_asyncio.apply()

st.set_page_config(page_title="المحاسب الذكي Odoo AI", page_icon="💼", layout="wide")

class OdooEngine:
    def __init__(self):
        self.url = os.getenv("ODOO_URL")
        self.db = os.getenv("ODOO_DB")
        self.user = os.getenv("ODOO_USER")
        self.password = os.getenv("ODOO_PASS")
        self.connection_ok = False
        
        try:
            common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            self.uid = common.authenticate(self.db, self.user, self.password, {})
            if self.uid:
                self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
                self.connection_ok = True
                self._init_local_db()
        except Exception as e:
            self.error_msg = str(e)

    def _init_local_db(self):
        with sqlite3.connect("smart_memory.db") as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS alias_map (wrong_name TEXT PRIMARY KEY, correct_id INTEGER, correct_name TEXT)")

    def search_partner(self, query):
        try:
            domain = ['|', ['vat', '=', query], ['name', 'ilike', query]]
            partners = self.models.execute_kw(self.db, self.uid, self.password, 'res.partner', 'search_read', [domain], {'fields': ['id', 'name'], 'limit': 5})
            if partners:
                res = "نتائج البحث في أودو:\n"
                for p in partners:
                    res += f"- {p['name']} (ID: {p['id']})\n"
                return res
            return "لم أجد أي نتائج تطابق هذا الاسم أو الرقم الضريبي."
        except Exception as e:
            return f"خطأ في البحث: {e}"

    def create_invoice(self, data):
        try:
            p_id, amount, desc = [x.strip() for x in data.split(",")]
            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': int(p_id),
                'invoice_date': datetime.now().strftime('%Y-%m-%d'),
                'invoice_line_ids': [(0, 0, {
                    'name': desc,
                    'quantity': 1,
                    'price_unit': float(amount),
                })]
            }
            inv_id = self.models.execute_kw(self.db, self.uid, self.password, 'account.move', 'create', [invoice_vals])
            return f"✅ تم إنشاء الفاتورة بنجاح! رقم المعرف: {inv_id}."
        except Exception as e:
            return f"❌ فشل العملية: {e}"

def main():
    st.title("🤖 المحاسب الذكي Odoo AI (Gemini)")
    st.markdown("---")

    if not os.getenv("GOOGLE_API_KEY"):
        st.error("⚠️ يرجى إضافة GOOGLE_API_KEY في ملف .env")
        return

    if "engine" not in st.session_state:
        with st.spinner("جاري الاتصال بنظام Odoo..."):
            st.session_state.engine = OdooEngine()

    engine = st.session_state.engine

    if not engine.connection_ok:
        st.error(f"❌ فشل الاتصال بـ Odoo. تأكد من البيانات.")
        return

    if "executor" not in st.session_state:
        llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0, convert_system_message_to_human=True)
        
        tools = [
            Tool(name="search_partner", func=engine.search_partner, description="البحث عن عميل أو مورد بالاسم أو الضريبة في أودو"),
            Tool(name="create_invoice", func=engine.create_invoice, description="إنشاء فاتورة مبيعات جديدة. المدخلات: 'ID المورد، المبلغ، الوصف'")
        ]
        
        prompt = hub.pull("hwchase17/openai-functions-agent")
        agent = create_openai_functions_agent(llm, tools, prompt)
        st.session_state.executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_input := st.chat_input("كيف يمكنني مساعدتك؟"):
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("جاري المعالجة..."):
                try:
                    response = st.session_state.executor.invoke({"input": user_input})
                    answer = response["output"]
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                except Exception as e:
                    st.error(f"حدث خطأ: {e}")

if __name__ == "__main__":
    main()