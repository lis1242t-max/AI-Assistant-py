import os
import sys
import re
import traceback
import sqlite3
import subprocess
import threading
import time
import platform
from datetime import datetime
from PyQt6 import QtWidgets, QtGui, QtCore
import requests
import json
try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from OpenGL.GL import *
    _OPENGL_AVAILABLE = True
except ImportError:
    _OPENGL_AVAILABLE = False
    QOpenGLWidget = object  # заглушка чтобы не падали наследования
    print("[IMPORT] ⚠️ PyOpenGL не установлен — OpenGL-функции недоступны")
# Импорт менеджера чатов
from chat_manager import ChatManager
from context_memory_manager import ContextMemoryManager

# Отдельная память для DeepSeek — изолирована от LLaMA (deepseek_memory.db)
try:
    from deepseek_memory_manager import DeepSeekMemoryManager
    # ─── СИНГЛТОН: один инстанс на всё время работы программы ───────────────
    # Это критично: _current_chat_id хранится в объекте, и если каждый раз
    # создавать новый DeepSeekMemoryManager() — состояние теряется и память
    # никогда не чистится при смене чата.
    _DS_MEMORY = DeepSeekMemoryManager()
    print("[IMPORT] ✓ deepseek_memory_manager загружен (singleton)")
except ImportError:
    print("[IMPORT] ⚠️ deepseek_memory_manager.py не найден — используется общая память")
    DeepSeekMemoryManager = None
    _DS_MEMORY = None

# ═══════════════════════════════════════════════════════════════
# ИСПРАВЛЕНИЕ №1: Импорт запрещенных английских слов (исправлено)
# ═══════════════════════════════════════════════════════════════
# Импорт списка запрещённых английских слов
FORBIDDEN_WORDS_DICT = {}
FORBIDDEN_WORDS_SET = set()
TOP_FORBIDDEN_FOR_PROMPT = []

try:
    # Пытаемся импортировать только FORBIDDEN_WORDS_DICT (он точно есть в файле)
    from forbidden_english_words import FORBIDDEN_WORDS_DICT as _imported_dict
    FORBIDDEN_WORDS_DICT = _imported_dict
    # Создаём SET из ключей словаря
    FORBIDDEN_WORDS_SET = set(FORBIDDEN_WORDS_DICT.keys())
    # TOP_FORBIDDEN_FOR_PROMPT оставляем пустым (он не используется критично)
    TOP_FORBIDDEN_FOR_PROMPT = []
    print(f"[IMPORT] ✓ Загружен список запрещённых английских слов ({len(FORBIDDEN_WORDS_DICT)} слов)")
except ImportError as e:
    print(f"[IMPORT] ⚠️ Файл forbidden_english_words.py не найден: {e}")
    print("[IMPORT] ⚠️ Фильтр английских слов будет работать с базовым словарём")
    FORBIDDEN_WORDS_DICT = {}
    FORBIDDEN_WORDS_SET = set()
    TOP_FORBIDDEN_FOR_PROMPT = []
except Exception as e:
    print(f"[IMPORT] ⚠️ Ошибка при импорте: {e}")
    print("[IMPORT] ⚠️ Фильтр английских слов будет работать с базовым словарём")
    FORBIDDEN_WORDS_DICT = {}
    FORBIDDEN_WORDS_SET = set()
    TOP_FORBIDDEN_FOR_PROMPT = []

# -------------------------
# Platform detection (для совместимости с Windows)
# -------------------------
IS_WINDOWS = sys.platform == "win32"

# ── Директория приложения (для поиска ресурсов) ─────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Логотипы моделей встроены как base64 ─────────────────────────────────────
# Для надёжности: не зависят от расположения файлов на диске.
# Fallback: если файл assets/logos/<model>_logo.png существует рядом — берётся он.
import base64 as _b64
_MODEL_LOGOS_B64 = {
    "llama3":   "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAXIElEQVR4nO17eXBc1ZX375x7e1NrsbxivOAFMMgGzDbsqEUGCJBvSAgtlglZCIHCTDKZDBDI1mriyTZhMgkJX/BAIDCFoZuBBAhMAowkJpjBwdjG2AYbvONNyFpa6uW9d8/5/niS8SLLMpVKTdXnX1WXpG7pvnN/99yzCziMwziMwziMwziMw/gzQFUpk1FGRjmTUc6oMlTpz7a27rP2/xZkVBlpNQf6vDHTajOZjyawqhJyB1pbKdOq9s9F8kdCeg/hVDXxxJvl4y6+a/msv/3J6lmt68vHqaod6ndHgtzea1c9sb58XNO962b93dMdx+0o6cz4HtvWj0jCR2ZOVYma84x8s9tUqJzwo9903bx8Y98l2wuYtrOXEGVgQp1iQo19Z+705BPzrxr7qwTROiDDqi1KRDrc+o2ZVtuebQpUtTrzcvDtJRsrzWt3edN29EdQZQlTqn3/qPHx1y+ahV/fcEJ8ARFpOqcm30zuL0CAEkCwgN7+2JZ5L63xfryyozbR11cGNAAMAVAgCACTxKhkFCdN6uu/qrFq/tfOG/eDcjA8CZlWtdkmCp5c033RLxfZny3pTM7q7AUgPsAAlAEVIBbB9Hrg7CP6X5l/qf+Z6Yn6DbmcmuZDIOGQCRg8ec2l8blfbvjJC+9Vf3nbjhIQlYCImRQcUiQACAQRUQgqsNOn1+Gymf33PHDj1K+UPGFV7EdCY6va9iYK7nntg0/96o3YE0s7qhlBOWALJiWW3YKzAqriQ2w8as+ZUtp525ne335i1qgXBwkcyX4O2TClWtqMfaLZfW7Blod/t6buy9s6+nyOixI5q3As7CCsIFWQAgowGJYTrOs39voLlye+fMODm56sihmhZuzlJdK5nGlvouDxN3s+s+D1qieXvh+jiCs7MtZCmRWkREYMAIWSgthG1IrzgvZ1ifE/eiX2dNvm8iXZJgpyI7Q3h0TA4L1s/te1t/7u7fi1nV29PkUpIgpSGJAySACSAEoSvkCAKFQC4hhHOnf1eY8vq/7Ul+5f+0PKk8u0tRkgNHj55ma3oqOUWrAs+siKrRHhGNQxG4KoOHXiQALLgSeqjgKCqkABwDL77uUN8cQP2oNHVUszm1dCR+IqR3wF0rmcyTc3u3/+7bYLfvay/+LmTnJsnZHdayiIFKrGQUhBDCZHpGQcEQg+FACDVTwOJh9hI188078qe8VRuUym1WazKVGFXvZQ4c3nNtfMZi2JwhpVEgTKE8ZGcGSkUI7A2642Oe3d/ji6dnmgKESVmeAANQHHrP3MzO72f2+uT10xAqM4Ig1QVcqvTKuqjn56Zfmxzd1EbB3rHgQSSLRCShw11dVxG48bKxQxTpwwBVCNgpUhEOKY2C07RJ5Zqr965d3CnCwAyyQ3Ptn545d31Mwh8RzIGg5UDFtunOH1f/0s/87WeTVzXps3ZtbDV8RPv2l2zzfOnFL2FVFmdQIwiDzrSn7w/Jaaxu+91HV9vpncwa7CiDRgUPWv/fna7G/WjP5Oqa83UGYLaLiEigCWjxuvmDvFa/f7e59MVMembi3UnLt6G5+xrdMDRUkVTKQKJQFDHJnRpnH6B6/81x3Hnnvf4o7T7369fvGa7SLGCquQgCOcmlpc+2+fi1w5k2Jv7ivX4o7+07/+rD7Wtik2A4AoCRMgKpbOPrJv5ytfqp1D1LJrOI9zUAIyGeVsFtr61s4JX3yo+511u5LVzD4JQAQDkkA4kuBzjqps/cplyZuvPWXc05UBpauKAnf/5655j7xa/Pmid31iVhUyBABEDnDsqmLWfP1C961X++oue3593ZmMigIMUaYzJpZ2PfmJ3lMmTZq06cb7NDJxK1w2C1UFNedh883krenqOvmm38ZebV1nI4ZBQkpwEiTr4vaWE7p/9qOL6v/+ymGugh3qzT3RhjYmNAW/eOnd27dWxtSC+gIBWUBDF4cEZk/w19191ZhPnjazZgUaW21jCmgHUMx26M0XjL73hbe7133j8cLCP63XWraqqmDVCAwHpr/k60NvVM/vrk4C4gGWSHxyk0c7Tje4awY3v+Am8nefGkEBePe9rpFj62npw2/03Liux/56Y6c6smzIGNPXFeiiDeYGUf0+EW1XVRpKC4a1AapK7dmmYHOxc8o7HXRTua8kzDChEAQJgEn1Pl01s/+q02bWrEjn3oqivSlozzYFyDYFQLO78T6NXHjcqP/8uyZ33azJzBKQMAUgEjgAFAGt21SUXTt6lCIEceriVdZcOqWQu/28US80ZlrtnpvfEzedRn5jq9rPn1L3cOrI/ueiiahRUadwBBu4t/pqqr72fO/VAJBqw5C2YFgCUi3hH/3oicI1G/vqqgCV3YZP1MWrk/zxhuDJli8c//qN970eyTfP8fZdY8FN5N94n0Y+d/60Zy89XjL1dUnrNFRHVgUkAooLc7GfTMUpnKWTx5RK910x5lbJKKdaUrLvmnvJmIIIlOadwv8wo6bkQYhJWYmYuvqAJRv9L6gqtafgwgj2EAhoz8Kpqn1jY/DZ3j4HMo5VASJVFUsz6/oK86+deGsgoIlbTz2gu1lwE/mNGbU/v27qXadP6GoztsYA4oQJgAttqWMEvQWpH2V4bl35ViLanJ4NyhINS0CWSNLpPJ81s27NyfWVp2zCkpIIAQZ+IJvKNSfev2zX2SDSdG7//R6QgDB9Jb3nma1Hv7crdiykpAQwAeHpJxN8zlTNTUwkNqRzytns8IKOn51XX4BvXD7ma8fUe4EGRKSkCoKqCdWh7MzceOeGe9P1DwIZzqUx7JqDaJg3jgRKV8zFv02rFajPBFaQdbLNi+ri9bjhQBs9IAFtaGMA+NP7/nXdfiICggs1SFXFmiMS/eUrzkn+AKrUsBLDZnYAkG9udumcmtTs+qXnzXT3J6uTrCpCJEBomxQgFLsKHhBufKRRWjaVcgDplQ2jXp1Z1bcRlpnECIi4UhZ6p4M+5lRjoSfY+xockIB2tImq8nsd3sdLXgBmJkCgRIJYgo4ZL69ddsKEd9ECOtjpD6JhJRQZ5QU3TLnz2HH93XDGEEmYLqgyiR+83VN/7N8/uuGLQFYaW4Y2XPuBSBszaomoWB2RnyaqGaIiUCYEvm4sVU1auKq7AQDSufxeex6SgIwqI5uV1du9hu5KbC78khKLgbGAEkYnFacdFXvGKajxUPKJFgBZkv/pxMRKclQsjJ3Dj4QIzMo9Pb6+toHuVNWa9ha4kRY6Ui2h1jRN81rHUgmqYgggELluiXHbGtcIADvHpUegAW3h+7nFPWd0uFqGiTjAgsNcnCckff/aC6qfA6BtLSO7pwCwKg+KGMIvXuyZ/56rS1Ay6lRowK0LBMzQklvbO3byP/7HjutBpKkRakE2XAS3nDN+1dhoaT04RgQRskChAnQUbcoAaL83v9d1HZKAbFv4dcX73tyCRyBroAyASJBI0tjqyltzxtS8AyjRQaz0IAarNc+v7ml4Y2f0U5V+X2hUwhINisAABGSYd/UUddHb/V9R1WQ7WmRkNT9SZFotE3kTamgpRwkCFVJl8YCN3WgIVKPIp/eSd2gNyLZIxACdfd5JFaeAVVImODYSiVocPSG+hIkE6UNQ/3weEQJ++ap/1zt9CWImpUgVNJkA7Q4vKJRJAnm3f8yMr+U2fgrZrDS2tI1ICxpTKSiAqfW8rDoKqAIKJgi0z6Mpy7dvnwTQXmny/htQJSArXqC13V50ljoFM9gYAyVLdXFF3MrTCiCdHtneczk1+Xyze26Tn1pVqvu0K5aEyBkhgiYTEKXdJ6wA2BB90F3RN9bjW6oab8+mHEbgFMZ3hNdgZh0tqTIKODBDCPClgOr4U6vi04HwKh6QgMzAg55d1Tuh4PF4qAORDYt8ZLnaFIOLjymsAQas+giQB2AA3PfH0m3vdBmFtaoANFDMmCBy+kyuiKca3gaCQhniy9q+sbP+5cXOZoC0sbV1BFqQBwD81QzeVGs8F4YtCpCgEDBWvi/j9/2L/QgYZOeNtbsmFwILWBJHDGGjiFgyFGy6/PTjNgE6IvcX3n1Ifm3xrGUdsYtdsaxMMAJ2JmF11mg8/oVT7e2jx9aRBBoQFFCGscDWnkB/80bhRlXl9rbhQ2IAyKXD+52aUr0hSaUPYCwpWAHSAEA8Zs4gADtXDqMBgx/uLMamBtE6gCAwAAwprMGEUdwZJSodTJhBNKyEMkgfX1L8zsb+qCFrRKFAoJhUAzp/OhbefNERC46u6+6EWiaQgBwANfCKsrFQe849L3ZegGxY9h7hY934GrtnUZTKHiAUnGAAtK/60BMMYcTaAADLNnm2HDDIMIjCF3ME9UndCQaQOfidTOfUZLPQp9/pm/unbfGP+aVAQGwIIohanhzpXXrHubV/IKLyGTPkgeq6JKuIEAKoMsgSthYieHp5z20Rhh7syhGRDnSoyk51FaIEVRUKg0xs2hV4+6rRfgS0IwUAmHhE9Wk+WxAZEBkIWGOxCMTZ1b4AIwmAGtJQS6QPv+7P31xORohFSYU0IBldx3T+Me5+Iqqk0znzvb8Ze/e0RGenwhhQREEAQUxQ7pf3CqMv+vXiwgXZLMlItMAS6bik8fas18EpFPFJTjWKhpXDaUCIziJFlAAwQZmgxGADHD8pUXUwAYCB0yeSZ9cXz17WnbjULwaOCAYQUWvNNOrd+P2m+n8HlFY2NJiampqdJx9JDyRrakgEDqpQKNhCNhWiWPhqz62GgHz+4M9WAOOrKRqWzynkMlBErZ0CIIZsVgYjzP0JyJKrigBHjgrmBr4fhulMABOBFNsLwYrwF9sOKogB8H/byv+4vhAjsqoKhShJdbWhUyd7jxBRb2MGJt0yO4Aq3Zae+OC0mt4SArCBgjQCMKwr9cnqzvglTy3tPRd5DKsFjQ0gAdBT8lZG7G4+AAL6ffi7fx7AkBpAAEQQARkMbB5ggJmwo0DbDrbxwahv4er+U1d0xz/pFysCwDJI4djMiPf5d1wSfQSqlGqBZImkMdVmThoXf/ukifJktKaGndpA2YMKwRqnGwsJPPxq77cMaHhbkAq/FEqV7WHuTgPGiiBDRJQHJACAATOYQxsAGBgD1Cc5ejACkAciBDy8uDJ/YynBxBSePuAS1ZZm1ZcXHh2vW4MWmMGCR1tbShRKnz07+c9Tk12BOGWC1TBAZOOXe+X1HbELHlvSfVpoC3LD2oJ4lKJECAuIRAANbbP3JyCTIV+AooedFAWUScEEGIIQ0OvxkPW5QaRzavJ5yD3/03v+W13VH3dFTwhkGKLqwBMi5cpnT5V/UQDp2R+eJBFJOg2+9ITRy4+p8x6PJpOsjh1g4GBA1uqWQjyy8LWe70YIaFiZHtYj9JXI08HoemDvzDKSomgLVxywvc+sMnsSwKzOAscdwScBAFKpoZ+cByxIn1jhz9/cHwEZ0TDnNS4Sj3LD2NJ//c2sCcuRHqJUnQ4rDl84c+xPJlaVfEXADAcjDgwyQbnolnfWffzBV3rPOaBHaAv3W5OITvUFAMIGJRSIRtlgn5D6gF5g6oRoFQFQJggTYABfga1dlXGDD9oXaVWTz5O7q3XnNct7as9zXuCI2IAY4ogmVlXkqhP5pwqlofKIfDM5pPN89XmjlhxTX36RYzWscE5YoerAFtjQG8MDi3bdFjFDq3T7qrDk4xCZ4QlAUAIEYCDG6AUQ7FkV2o+AxsFvhFeHVnTAhBCR5wFdnp4clsux1+llMsp5gqhq8qX1VT/r6GVlIxS6ocBR1Jo59ZVlXzpl1O+RAR2oUdHYENb3rj+39hdT6nxIYAAaPDgyrlRw6yoTL//poq5r883kMq0fTqAQAchDnGpke09lEnwMREcsFAHiXHrPEpWQzvNgj+CAGjAxUX43zgrIoPlQhifYWozN7e/vn5DO5Xn33I8qPXskTNSQ/sPvu+9ftLNqLCgQqDIRIIHB1DpBeq65xxMg13LgKLI92xQgnefrzhr9u6mJwjMcrzKk6oBQk40l2rizqE+9Vv6BqtZk29owmN5+R5QzCtqBvtFbS5EZCBxIiZUI1gBHJG2HAnulsfsRMFhaOnlcZXVVUJSQfoWCCOSCzV511bdfrszLNze77DYY5NQgBbPkJvLvXdx1/XPrR11dKviOmM1AocdRLGKOq+5adNPJ1Q8ho9xMw3dsM7m0OgWuPNVmJieLcAFoDyPORIEs3jF6ymce2v4dZJuCbKqNkVaTbV5ps0Ty05eCW7YFySRIg4Fyq8Yt4AS/FwCN44ZJhgZLS58/+8h1E5LBVrAJEyIAzGr6egP9w7rorU+vL38yuoB8NJOLvUzBI8uL1/z8teh9a7YEjmNgcgoQQUQxo9bDVSfHvu0JkJ598BwirPXnzG2XTFl63lH+i7GqKlbFbi1gJtPT1+9aNyRvnf/Crjur/tgUIE/O5ud4f9hQ+Nhzb5uv9vYEyqwG5AAxPIYrcuEs9xYAtKU+LOMNLUwuZ+zVze7TC3uffmJDzSfE8xyULVRACogyTjwiwF8d6bVOrpe+d993da99UHf+2g8UbERFwy4wQQMTj9nLJnU9/sx1o68eSb9+EAPBlLS+23/qvIXFl1dvQ9RElRVESgARQ5yVyeMMnzmxb9GcaZHOrV2IL94evXDZB0kY8tSxISIR1QifPqawZfHNtbOIUAqbO6ENGLI5mk6nkW8GZo/WBW078H92FA0xO0AVQgwi0Te3KFbtqm2KRBQVjyCVkhpLpMKE0HOqCyyfOqofd11e1fIbKDWkR1ZAAUKPkMmobTqaXr/+wQ3/+n5lwp29PYWALSyBocpgK7yl08mTxVFnP/s+wZcIXKUEjpXUcTTcopBEq4jHV7kcERUbM62WqGl3qjykEcwDAih9+69rX5weKbwHNgyChPNPCgUTxywFge9KRc+JCxxbS6IGwgyrgDhytTXMqamVO06qjb+dzoEP1ubaFy0tcOmcmgc+f9T35ozatQocMVbVhU5MB40iw/muXPSc88uOowZAlKAGRAFUlSYnHK6dY58CgFtmpw6eC4SNBhgiKv/1dO+usXVKEsB92F1WiAKkaojIEMQoACWFEYGQF1A8Yj82sXvR3ZeO+aEOFfSMAINqSkR9X00lbp99hCHPRYU50IFu0kC2J4bBhghGQeGEDjxAjeNo1Byf3NV6/Rm1f8xklPcdoTugG3z5LgoyGeXvXjzm0Usn966w8WhEVAMmgFRAOlDIVQIgUAgoLG07CeL24qn9lXuak7cIlDK5kav+vgh9fattPm307644vu/7E8fHIq5s/bCjFE6oDHZXKKw0ggEYqIpv9OQxZXw1FftmxQGrhjDAByRAFUALQAT3w0/XXXPRUeXNxsaseOoTkWMO8xQMGCRDUBX1nY2bc4/yi/POCC6fHIsty2QO3uE9GFpSKZfOqflx8+Rv3HBq8dkpE+ui4hsA5AygIIZyOLNCgKqqC3yDoyezvfL4yjcvnF73au4ABvjgIzKqnCWStZ1bpnyzdczjr26Ln7W5G0ClDLAFIBicdBg9inDS2P4Vt58nt1wys/a/c6rmYD5/pAgnPFpItcV8/bcdt//HcnxzQ6ku4bxSKAcrQAyYGKI1BrPqy6VPH1u57bsXjPrFcN5nRH03VWUiElVN3LO4NO+FNfTJrlLl3O19irJYjKnyMbUm2nHKVDzWcn7PHUSTipnWVpttahrRtOahkRBe/keXbD/xD2vj39vQUTlvZ1Fre4MoquOCidWR7hOnVS+6YnbfPzVOrlv0UeaHh0Qmk9l9XaoM8IHq8Y+urMy+66XK7KVama2qYwc/P9Sp8EMB0YfrWwCqOum/txVm/9PL5Ybnt1Vmq+qRgw//s8uhOjCfP8Soye4H/oVm98M85ACToIfwDxUfWdh9H9CC/Qef/xLIZJTRsrcgI51XOIzDOIzD+P8e/w+ygQD+jNefTgAAAABJRU5ErkJggg==",
    "deepseek": "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAQi0lEQVR4nO1aeXSVRZb/3arvrXlJSEJWdoKoQbRbe9xGhjhweprTNujxvKc9tqitDS6Nrdjigvq9r91XVEZtaccFddp5T2lX2taxDQ6ijIiiJAo2QoCQfXlZ3vpV3fnjSzDIlhDs6emT3zk5OSepurfur27de+vWBwxjGMMYxjCGMYxhDGMYwxjGMIYxjGH8H4CZiZnpIKPI+fk7QTDCcrrJBvCNTQci4buy/LDLZWYKRaOiorqQgMp+/6lCzZRKDgIIhUj1/dWQQMZuywVakkSTU/uQSMxRsejuU1YKzjx61/UTXo1GIfrL+JuAaZoiGGQ5kLFuF/Dof9T/89V3tz58yeLGdRfd1Nlw2W3Jprse/cu5ABCJOHL65D389JYTLzSZ54frnweAoLnRPRA9wSBL0zTFgcYYAxE0EEWWRQqwwLwx8OCzBVOaW/lIg/QErdlIpNCtOLNrbImoSyTUhLrW/PmrP8n5h7QWSKUBwUBRXuzTvFz5KTNTOBxmAKiocDz0612eWZ3dUDlG1oyabTWlFeMr6qebbKyyyN73ipgA4mj04F4ypCPAzEQEAki/+PqmiR9vKry2ud2Y3Z10l7HwQDNA/M14Q2hAC/SkgIwNFgI2AMrLiifO+ZdtU8+YMaXWNFlYFmmHWZaIkrrMao40tI8MaqUxemTPhpMqeubPDZau7TMUYIpEIKqrQfVlH9Oy+SfYUhDfvKTlcSK13Lyy+P095PbDIXtAr/EgIh1esn3Rq2vyb+5OZQUySUArxST0bvb7WGYNwUIzkSIpDAFiQUJI5tTO2TOm1M6bt85lWZTpmxcEEAUQj2sPEWBrndnRkn1c5zrXB9ff13DPndfQDeEwG5ZFdiiE3fo8LmDBrU2PbOsomBdAcyuA96sAAeDwEMDMFApFBTOw6O4dT2xqGH1heydgQNtEWkopiEH9IjyDAJAEHIdwOcQwpMpA2x7fEUuf3zz9ivMmr5o3b51r2bIfZPrrc7lJcxogCMFK6aZOL7P0XnfzQw09t1l0K/NG929fKJvV0KInpFMJf0fcM2trU+FpBNglpRQDnHC8ah+2HBIBleEq+d6LIfvqO2ufaIyNvjDWqTNuoQwFl+EQ/W0QeB9/ZRCE0NQd98qPakZFlz7z9fkLLpj4J9N0drWpNwZ4XZ4GKQCbBYMgPaR0e6dUsL3zo69veutya+TD3am8E9O2cyCSaSCd0ZmcAFx+b/wLAJgyZZ9LGDwBkQjLUIjs8ANbrviqcezFsU6ddgl2M+QhBhQigubmDn/huk3Fb97zWO1Fiy6jp02TDaAKqwC4XbGPJHIu3T0DUhAz4klf8RvvF7/f1p0rbVsrScwMgiCQIHKRiiUnjWlZBwDV1eF9EnDAFPFtmCaLUAh6xcra8q2NI+/p6IIyBLs0JHhwovoTAECQYK2b2/36821FT1lLt5xtWWQDhQIATq6Iv2uILq0YEmBoAARCWrmNpo5cyQpaCiFB0iASBkPAMEgH/PbHP51zfD1MFpZl7XX+B01ATQ0IIP6vj1y3dWVy/AYUA/LwFFMkhBSamru8ekt98X/+9tkvZ1jWMemgudF97plHbc0fEf+DxwMCf5P6CIAUzkn6RhBDa2h/FsS4svhDRMQmqvZr54AXbzILi0g/94ftU1d+MHJ9R5dPGEKL3vB2aEbvE1ozBJXkd3accequU86cdfQmBFlGzv961Jtri2rqOwJZBrQGxF5GERiaOe32CHdZbtPbS82iWeEweF/prw8D9oCqSmfs+s3eeRntMyRp7bj94a6mSRBDN7Xn5L3zcfErzKuzEQVCs8u3TxrfGBoZiNuAIKBfUGNoZtgZRcrtE+7i3JYN58zYfA4RNBA+oLYBEsC0ahXZzBvdze00K5UEQACztpWCVgzFGjYDCmSzs7Z9xpyBEAAQpNbKrmvNO3LBreVPMZPGdDZu/MWklSdMbj4ry5fJaA0maDAYwoDw+WAU5mk5sbjh9/Pm7KycNm1au2mGaX9nvw8DygLBSFREQ1CP/957rFbZ5Wkb2uMShs/n7D+zU2FkbMBOG2ANJcgmJiEGF2Y0O4UxC0HCSCVhN3WVnH31nfXLuSp6MRGQ7aUaQBHgIg2tXQZRYXb36oK8zHvHTuQ//etZpf99H5y7ycGMHzABFdVBAoC6Jv+JNnsgBVCQ0/lFeWl6qXTrrzWRTHRnJqdSvumtnfLERCanLJ4wkFbQUmjqddkDgwEmQUQgrYgFAVLCiHfD3qlLfnbl7TOPWPFGzdwNX7l/yOR1EcFmTcLlkjSqmK4zFxR+0CtIMIOJ9n/uB01AVe/v9m4xIa0Anw+icIT+3eJfFj7Wb9hKAA8yb8l94MnknNpd/itaugInxnoEBCtFgiTzvr2BAZaSKT+rs8nlQndnPHtiT1IAWrGQZCQSUNvtvJNerJKfALI7HmcQkSSWrDTQ0JLIcuqGamFZlKZBhKWBFUJVDgWJHlEMdlze1ukC02SjLR9yWins6mqQVRNlovIYgOXMePbex3ect3lXzl3tsZxR6bStIEnu3dTRDAgU5HTX/ftt702WNDt++7LaOZtrC5c3d3hzBNssyCV1RutYJscvBPy9tBGDYCCJ0uLO1lsuL7FNcz8MHwADmlBUVMmOSnee7iUgkUKBZZH92QqoUIiUZZGNaEgxM0UiLIkYiy4d89xVoS9/MKao4VVvwJBakU17BUhBAFNHtyv/iltnvrvovoaFN8wb98rJx7XMLshJpm12aQAMIiEIDO6bTAwCCaR6jpuc3AUA4fDgI++gGFO9Fy6tgXRKjAWAVav2VEpE7HRriE2TjWOOOanh324unVNe2vhYTjYMzWQT1B4kEAi2zR6NVHNbT+H9N91XO3t+aOyqMYWtiwJZkJq17s0s/YsOJgF4PVw3e8aXLY7uwZo/QAKamhyl6SR1SgFkMgDDfQzzZg9Aan+1gGWRbZosbM3yroUll08obnjA74OhWNj0rTlSQk0oS61JJuPpNLv9psnirkVjHspxt6w1DCGJ9Lf1aGkAPo+9mSikHPen78oDqgAAOYFMnAjQDJVMydHPveIuBwDT1PuVY1mkmaGnT2fjjmtKrxlX3LLC7xOG1kr1vyPayuv6sLr49owdcOeNQIMFYPFiFkeN67wt22tD2UR71D7stNZ8Wck1g7NlTwxoUmVlJQDAILWDBCAIGZuyRM1meXyvWx5QDhFxVRUUgizvubZubn5Wx2fCJSU4s0eqyiSRyiigpUOcC4u0ZZFeNK/8da+naxMZUoC/SW2aISQ0xhbxGmD/192DYVCsFYyUO6RwarW0DbR3+c8iENfUHFw5EXEwCBB9r+f4ithFub6etILRLyISSLAnmVC6rqlg/k3319378ts7v3/7I1/NTaY9haTBIN13BrSUEC7Ruf3Kf9qyFgBCob27PQPBgAiomRJlACgrUJ9LToFZu1RKI542frT600+LolFSA0lB0RAp02Rj/rnj148q6nwwK0v0Brg+EIQQoqub8GVd2a9XvFO0fsO2Sc/Euv35BOwuqAi2drvBI7LSb9KE05NO93jw53/ABESCQQ0A83+6rdpFyTophQA4k9A5/tfezg85o/Z/5eyPcBgqGGR550J5a463rZaE2KNX53SJBBIpqJYOF3f1OCmjf/mgtBAew6bxpYnlAJzm4SFiQIt23Jcl0amJrKzUKsMFBhGnEkBLLOtqJxtUahz0ecuRVVFRRUTF3RNGJ67PDoC0Bn97AwUgpWQSBIk9w78y3IKyvW0fX33JuA8AU0SH8Egy4BhQUVFFADCmJPOy1wNSGlJpqK50/kRrqW+uZZE2w9jvw4hpshHsffCwrNPtYJDlLZeNfiHgaqpyeSCZeR9G7M2n0ho+j6YxxUmLiHQwEh7SfXzABITDlQpgCgVTb7nRUSeEEFIAnXHo2sZcq6ZmZ4FlQe/vJcayyHZ2ikWfpygNHDOJFnpdcc3auWEfaA0MrdweIfP8rX++5ZfjXgsGI3Iouw8MggAiYtOELM8vjxXmdT/qywJprVlqxV3J7NLHXpT3A6Try8L9vMAxNLJxo3vxA1tvfPiZ2pkAaRBxRQU4GGT5qwuKPinLb1vmzxJS8561wbft1yyQ64unT5maWqiZqSISPNSmw24MKg2Gw1BgpovOy3k8YMSamISQBErEYTd1l1xw45IdVy2bT5l589gFAKbp+PD2Nfb47Y2jb/+f6tFvX3t381ONGyMByyI9cyYETBYX/rj9xoC7rZaElAy9j3TGUAydnQM5vqTturlnj9kQjEBYA7zyHjYCiIiDUYiK0bmtE0rbr8/NhshoaCG17OmC2lZftOSOx2svWLaMMtOnszFlSpQA4MdneeqZu5tbOwVvaRx5YfilH364/LVNx82fT5kF+XAde+yx7UePa7kk15cgW0tF0HvsLIOUzwNZ6G94xvrVmAdNk91Ddf3dNh3KpGCQ5YqXSF0ably5q61olkpnbCaSmg0ekZ0WR45tucq8YtRDDOBHCzZ7fj7tCHvt180PbWseeUUqQUlpwJuf3d02dVLr3IUXjX8jePV2X3TJ2MTiJXW/2dZYdnN7zM4YklzsxExWCpw/IsOzpzfOOWfWmDccdnbX/kM6BodEgPPQCF63blfB714NfF7XnlNC2laAIZQCjxgBMSq/7amLzuhaXFExvh4Anntl2z+uXDNudSwGLaXNNgw5MjuJo8d2XHzD5aVPAiyZIX59+64nd3SV/SwR0xrym84vseJAVgoFI9JvHjUuee+C80vf1UOOAENo6UYiERkKhdSzL+04+c/r895qimVlC7aVAMk0k/J5hcz1drVn+1PvBPyqubHFM7Olc8QRmsEEJobSShvIz9ViQtn2xb9ZsO0BotOTALDwjuYntjaNuCCTNjRISwKIwGQzyHBJ5PgyKM7reOnMU92/OO203A7AOZ5/VQIcEliGQqSWPru1cv2mghXNsew8KNsWZBianVcTtxsQEsiknN5Pf4UEzbYSnB2AyMvu2DwiJ/VyIIu/KClA82ebXI/VdxSMUWmn2apVb+tEK9YsqbgYOP24rd+be/bEDcFIREZDoUOKCUNu6vc9ZD79/BcnrP3LqBUN7dljUykoQ2gCQJqFhpMPBRFE/21yCnsFxVCCpHT7ABcDZAB+0dg1vjS5uLXTNzMW9x2bzqDItsnldsH2edGQn9314p3XrL4BCOpD3f3daxgq+jzh3XfXlrz6Yfljje0FZ3b1AFrbSgoGQIIhnPvMHio1AM2CiRXBTjNkwC9lQVbHhlOmtJ3/81D55wDAHHH/seqUotoGwxg1WuufnPZ+A1EofTjWftiedYLBiIxGQ0oQcOsjO8/d3pxr9sQDR/WkgHQGYM0ASPVVe+y8ZJEQEMIAvB7ALxPxwsKeJfcs3HgX0endzrcCJyhg73zfp2+o6z6s71r9P5lhXuNb8uSkn2ytE2f2JKgylfGXsuEFO0+7IAKINSQSMZ8n82VBPv9x2tSOF2bNmLgJ6Ms0vYYzkxkOU98zlxV2LmOHY83fyed3wQjvUaMzbww89Vre5LaYe7RKiDLp0lKI+M6A32ibeqTcPO37JY127+hgkGUkgiGd678J9LXHMaBP55hMk41D6esPFX+VT0+ZmcIATYmCqqsdnX09vGDw72C3hzGMYfy/xf8CHEwD+GU6X+QAAAAASUVORK5CYII=",
    "mistral":  "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAL60lEQVR4nO2aXYxd11XHf2vtfe/MePwRO3FJCk0gSQWtC4lUKCBQ40ioBKlCSCWGCvGESpCgD4jSByTkGClCCBGJhz4QqShPVBoLEKKKVEQVW7QImqRplIbStBClSuLajj9nPJ575+z15+Gccz9m7ozvndgF1PlLe86dc8/Za+211/e+sItd7GIX38ewaR+UtO2zZqZ3zs7/fR7+13Cjxe8UU07qSOXgthOZXboZDG0HSQvAPCAm837FzGKWOfP2BJeS2bFy5dxnfj8ufeKP+1culsCSM9Q00Y/ugft9dfnzv7tn30c/174zCxPb8yAzM0ln71x+61Nf9vivg6IjaDRCAFHm93TT6toP/y3YJ7T0q8mOnZyKh20FAJ8xgFR9827X0sHuylU8NV9ZTTwK+P57iPIT99VfvHKTVfVxA9Qnbl8s/36vr3wJ0vgTKmAJ5tc/fC84cHLq2W8ggBoW631kknsVYbldPBhuUViz1Pe3XgI4dWpq2jOhS676/YhucQscZ6jpplQoSmHem3XeqQTg5gaYKcw9GSMmgMIwzDx3ZiU+C3pghhwCw4fkJaQwtzCbIaq18Bs/0sBguPMTIH0PQtAoiZohtfd2SH0qDdiaiVF+4paEqa15GHHE7ebsADNpQPFmGAT1aAlL/UqS7dv3bpO0aUxDYvJ7R5rr+mAOYYNh5jULsh3JYDoNiFrEHj6wvzoQG5UK2Y25dOBOM5OOU+wnH9ukJhJmtq2i2haZXAFY07cr2uAnRxaoyQYk4bfUBFIzMoA3uy7CrBaOZWLvPR1JHSDrcaqNU5jZ+g2oqHl/IxyIddiv7jwqEAla+3cZFg5ZUM2uA9sL4FR9qVYcVg1ddORgqv2tyYCU1s+epZM++yc9lj5tVqGBlhgylbnFuXT55T966rYf/9MnNiYpWlpKduxYWf7W08d4+bE/7109V4yUBDWteiJI2uPVfxNVwqwWgLVqL+CKKN2Z1z+dBmgFuBz4xQrcQSMBwUSKZTr2zCEShza9HMBeJx/6rV+B9ASvnBxX1sN14rTee+1eLv/d3XNvv70p0QGg1AmPLIGtN9QdNXbl1wMtzp6ATmcC7mBe76sZqs2ycTqOJQg68giNe+gERCFyctPK5MlPARArl9+iyoFbFcrZpbGAE5iRi0HBY+j2wxtn7DaWH0yL6d6I4ZrqaO8jQ40TKgZyIa+9lFySY+YgN9kWtI7WJFLuQDhFbqU4EY6GwyiGarOTiWgGUi0KE2KmOgiYKQ+oJWA4IrDWCw++bYnX4allyNQmjpP0GgaORhJNENDAsMdhI58MMIHQ4P5OwuDsOjMgtRW58STle4Od52A7E4DazNcmjMkwQFo3jjw68aEd7sQ7xnTV4MhfoMlonFoVt5G+AAvAiCjRJDqFYRCxFz532gArpRp4vcmNrY11QFMFtLdVR4VZMV0YhLrgTsN6y0gj1AfrGXmjEY05wvB9t803HZ2wvNCWrfqpp32dFHQP/UjmTKemgYHZBksaatyY0EXtZ2tXO+PypxRAXMvwhtG/ksB8hDEbuYwSH7IoWTJVqi59+UOrX//4f/p6VV3660dWMBECNwiEPffMXdXyMpSUake7eU62KDgl4XucuKPJA6bvh0wpgOUKzq3jy4FZAmJkw22sEh7XBcOakmn+3L/aYv63uzFvAkIbV5vdXl+n1PHd6hxytPZuPttkB2sYrIg0f4tMwAlwx03UZmwTNmcYBgdhyag1BvA0D63kQsTG3fSuucs223oNbelkG348cOamWc4YdtAPmIS6LG0/b/gGGOQJ3u7m6NKGVwMcswkL3arfItXuUBDlliZCN8JkBzQ0jw0qs817szWXRk3lFpnAdJi00Enf32RYGz13lgzdBAHshPC070whtHeYeE4XBQBcwz3eGJ9N1F0yxcTFCZONFAOT/RwmFWy8whh+NJPlNMyjNr5fl2GzYoZyONdBe5OfVr3shDO/4IM+Vcuc6oqN1V49D010aB6L9jECm+smPG3Oq5rIQa9gSiOVX+NgHciJnbRlp+sILYNeN8rlDrI5xnemSAuL1nvk116N7sLLVJVhox26QlrYm+2l5z8y/+IXF+jMN5usJuQ7VD2uv+e+0M987Iuq1q4imZmrdWpSoG6ej3/6h188cPb1HJ0ORCMAqzPAlKFqVnPyZidC1TLYWYNLDm7EiMOzdcXcXbel652f/9Shj/z6P06cwPZw4S9+42t7L+QH1twiy71VpeKouy6r9u9fOfgLT/yyma1NnGNuH2/+5t1vHTxvd1XJwgb5LwQJUp9yR3/6lTeYymocB3eUDUvCk+FuJLf6rNCD9YuvdrREevUvH5nTEqkdzx4nK66lXPWx7Lg5ZmAmzEUycE8UMt9lZb+WSHr2oTyY4/nf7miJdHXtm+/Ltx28s4oC2bxu1Apzx1NAdtxmbwrO4DaEyesO7JgTNCCh7qLsGOXNiz9d7BiD8fAJis0vFpFA3rgFURCV1c21IiGcYG/YMQpHTw3e54N/VewYpc9e3LLRtMrqRlHDihofodkToRn9ptDI8buAIGZoRNXdomi66bUnaI+3NnXSx9Clq5E4tOG6c8yUBww9tkbozxaIB0Xt4EhPU61DzI1UXD64O0w0dyaMgQY0tdbY4MxKfW2aH7UGaPj0SB5v4SawfWfOjM1xHExr1wbchdUBTNYUgq0QMK61dB9/fMgDJ01gzkpO7o3WqTkVbsQ/0m8VlR2esBa1zYStBGBDngbj5FMvhIGi9Gv7UkVIBCIUdSxW3ZZUb60Y6M+eeipG5zgBYZ25uoWrqICCKBb1kKuYKKaI6urV+t0TJ4Zz2LFioNe5dKZ39cLFlB1pXbIKWdW06BtjVMEwPdxY2MZB7S3GhJABrNsler1J/iAJdOHvnzR8Ac+rZGusxprub3ZSziy+/0f3SHIYaxXRqs7lJ39njvluno+E+9DeZY51OoR39r5v//7UzDGhGUDvnPJa6syRktfKI4GaczvLdPYctBEeNiEvLoatrm5w4e688MnHnj5w+bs/V1UlNDAwgWTKWZ2VC3fsf+3F27JMYWG0qodhgXrzc3bt/g9dFHZRiqaZpWaBCYox9+B77cCB/j979+B93unkth9g7kbprV28Uu3tvfTtd/v1XiVwq5eHMCtmSh3v7nntq3cvXHgbS4m2LcGAj4qrd92z2nvXj71F6de/Kxrx8RYV5fYfXLvzsd/7pTseeOCN9rdHGc+Urz33gQOvPn//9RGbGG1NVIKrCVJ7fmvDkrXeiWUWvvPMITcODe26vlbA7cl57dyDT9737Ff/oK35B7O7QYjn/vDTH/+hL33hb/pXVxgomYY8uKBvsJyMPKJgLS1h2MVv7Nn/9W/cv3HnZaAexJEPkO2TdwJvtK9mgG7HVqt5i6JcqlqnNsJGM203ITVnhF6H4NJxlU1dC8OIqsqdnDrd/OxD5MPn5Uf+owxs4JWPkY+cpHqRshjzC2G9a1XlOW+MLIZwMzfarhSoORw1msOrhPqTQpI5UFQcU5kbi7f1cZ/kFnIpHGnSsDbaSVDCCNVESzTNGoVNelfCpeLI9fBpqvOHB2lAGMT59z8UtQ4QKDwGfIyPQB4REKIUKAUiRNWM+lhSE3lAckXUR3Yb2k2DPGBoUzercbFRGbZPl0bVbtLvKIZ5w7gbn47brZ/K008yK9q+7kaW3zl2xO8WLNzyE6nWkcUU3Yo2Q7w1GzIZjQmork1Q0SZH9g4gcFRFCdD2LVtzhUGVRDUIkRszgU2Nks30Nj2juuVggQI5Vm32Adete7CTc57znHf6Y6OtOJLIe3JmPXX3bvfkemFhLndzv5NyJyVGj713LIDWb7hhpaJnXVTWxn5GkomKzgd/9rNvvvfeB6OKUlAiGDeO9v92D33k/lb/N58TlPPz3dTfd/DzfOFfOHr0eHD6xGDqoxwNOI3d+56vfOfDjzyt1SsRluvoNHt1OxlmcoLY+65rKX7gW+29mzT7/28YwNKjj6bDJ0/eXFc9iofg6NHjYSdObLmnx48f96OnTjin6+c5fSv4eIiHT5/evvGwi13sYhe72MUuvm/wP+b3Jjmq49qkAAAAAElFTkSuQmCC",
}

def _get_model_logo_pixmap(model_key: str, size: int = 30) -> "QtGui.QPixmap":
    """Возвращает QPixmap логотипа модели. Сначала ищет файл, затем base64."""
    from PyQt6 import QtGui, QtCore
    # Попытка 1: файл рядом с run.py
    file_path = os.path.join(APP_DIR, "assets", "logos", f"{model_key}_logo.png")
    px = QtGui.QPixmap(file_path)
    if not px.isNull():
        return px.scaled(size, size,
                         QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                         QtCore.Qt.TransformationMode.SmoothTransformation)
    # Попытка 2: встроенный base64
    b64 = _MODEL_LOGOS_B64.get(model_key, "")
    if b64:
        data = _b64.b64decode(b64)
        px2 = QtGui.QPixmap()
        px2.loadFromData(data, "PNG")
        if not px2.isNull():
            return px2.scaled(size, size,
                              QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                              QtCore.Qt.TransformationMode.SmoothTransformation)
    return QtGui.QPixmap()  # пустой — покажем fallback-букву


# ═══════════════════════════════════════════════════════════════
# Apple-style Font System для Windows
# На Windows: Segoe UI Variable (Win11) / Segoe UI (Win10) —
# ближайший аналог SF Pro, с субпиксельным рендерингом.
# ═══════════════════════════════════════════════════════════════
def _apple_font(size: int, weight=None):
    """Шрифт в стиле Apple: Segoe UI Variable на Windows, Inter на других."""
    from PyQt6 import QtGui
    if IS_WINDOWS:
        candidates = ["Segoe UI Variable", "Segoe UI", "Inter"]
        chosen = next((n for n in candidates if n in QtGui.QFontDatabase.families()), "Segoe UI")
        font = QtGui.QFont(chosen, size)
        font.setHintingPreference(QtGui.QFont.HintingPreference.PreferNoHinting)
        font.setStyleStrategy(
            QtGui.QFont.StyleStrategy.PreferAntialias |
            QtGui.QFont.StyleStrategy.PreferQuality
        )
    else:
        font = QtGui.QFont("Inter", size)
    if weight is not None:
        font.setWeight(weight)
    return font


# ── LLaMA-слой вынесен в llama_handler.py ──────────────────────────────
import llama_handler
from llama_handler import (
    USE_OLLAMA, OLLAMA_HOST, OLLAMA_MODEL, SUPPORTED_MODELS,
    # llama_handler.ASSISTANT_NAME — не импортируем, читаем напрямую: llama_handler.ASSISTANT_NAME
    AI_MODE_FAST, AI_MODE_THINKING, AI_MODE_PRO,
    SYSTEM_PROMPTS, MODE_STRATEGY_RULES,
    get_current_ollama_model, get_current_display_name,
    call_ollama_chat, warm_up_model, unload_model, unload_all_models,
)
# Мутируемые глобалы LLaMA — доступ только через модуль:
#   llama_handler.CURRENT_AI_MODEL_KEY   — текущая модель
#   llama_handler._APP_SHUTTING_DOWN     — флаг закрытия приложения
#   llama_handler._OLLAMA_SESSION        — HTTP-сессия

APP_TITLE = "AI Assistant"


# Импортируем конфигурацию Mistral Nemo
try:
    from mistral_config import (
        get_mistral_system_prompt,
        clean_mistral_response,
        MISTRAL_MODEL_NAME,
        MISTRAL_DISPLAY_NAME,
        MISTRAL_OLLAMA_PULL,
    )
    print("[IMPORT] ✓ mistral_config загружен")
except ImportError:
    print("[IMPORT] ⚠️ mistral_config.py не найден — Mistral недоступен")
    def get_mistral_system_prompt(language, mode): return ""
    def clean_mistral_response(text): return text
    MISTRAL_MODEL_NAME    = "mistral-nemo:12b"
    MISTRAL_DISPLAY_NAME  = "Mistral Nemo"
    MISTRAL_OLLAMA_PULL   = "ollama pull mistral-nemo:12b"

# Импортируем менеджер памяти Mistral
try:
    from mistral_memory_manager import MistralMemoryManager
    print("[IMPORT] ✓ mistral_memory_manager загружен")
except ImportError:
    print("[IMPORT] ⚠️ mistral_memory_manager.py не найден — используется общая память")
    MistralMemoryManager = None

# Импортируем конфигурацию DeepSeek
try:
    from deepseek_config import (
        get_deepseek_system_prompt,
        get_deepseek_math_prompt,
        clean_deepseek_latex,
        detect_user_correction,
        is_simple_arithmetic,
        compute_simple_arithmetic,
        is_garbage_math_response,
        sanitize_deepseek_math,
        DEEPSEEK_MODEL_NAME,
        DEEPSEEK_DISPLAY_NAME,
        DEEPSEEK_OLLAMA_PULL,
    )
    print("[IMPORT] ✓ deepseek_config загружен")
except ImportError:
    print("[IMPORT] ⚠️ deepseek_config.py не найден — DeepSeek недоступен")
    def get_deepseek_system_prompt(language, mode): return ""
    def get_deepseek_math_prompt(mode): return ""
    def clean_deepseek_latex(text): return text
    def detect_user_correction(msg): return False
    def is_simple_arithmetic(msg): return False, ""
    def compute_simple_arithmetic(expr, language="russian"): return None
    def is_garbage_math_response(resp): return False
    def sanitize_deepseek_math(resp, q, language="russian"): return resp
    DEEPSEEK_MODEL_NAME = "deepseek-llm:7b-chat"
    DEEPSEEK_DISPLAY_NAME = "DeepSeek"
    DEEPSEEK_OLLAMA_PULL = "ollama pull deepseek-llm:7b-chat"


# Импортируем модуль для работы с Vision (LLaMA 3.2 Vision)
try:
    from vision_handler import (
        OLLAMA_VISION_MODEL,
        call_ollama_vision,
        process_image_file,
        is_image_file,
    )
    print("[IMPORT] ✓ vision_handler загружен")
except ImportError as _ve:
    print(f"[IMPORT] ⚠️ vision_handler.py не найден: {_ve}")
    OLLAMA_VISION_MODEL = "llama3.2-vision"
    def call_ollama_vision(image_path, prompt, max_tokens=800, timeout=120):
        return "❌ vision_handler.py не найден. Скопируйте файл рядом с run.py."
    def process_image_file(file_path, file_name, user_message, ai_mode, language):
        return {"success": False, "content": "❌ vision_handler.py не найден."}
    def is_image_file(file_path):
        import os
        return os.path.splitext(file_path)[1].lower() in {".png",".jpg",".jpeg",".gif",".bmp",".webp"}

# ── Диалоги скачивания/удаления моделей ────────────────────────────────
from model_downloader import (
    check_model_in_ollama,
    get_ollama_models_dir,
    set_ollama_models_env_and_restart,
    delete_model_files_from_disk,
    LlamaDownloadDialog,
    DeepSeekDownloadDialog,
    MistralDownloadDialog,
)

# ── Система проверок и самовосстановления ───────────────────────────────
from attachment_manager import AttachmentMixin
from error_handler import (
    startup_checks,
    check_ollama_health,
    check_database_health,
    check_settings_file,
    check_disk_space,
    install_global_exception_hook,
    guarded,
    safe_call,
    safe_db_connect,
    safe_json_load,
    safe_json_save,
    log_error,
    load_settings,
    save_settings,
    build_fatal_error_message,
)


# Google / DuckDuckGo helper config
DB_FILE = "chat_memory.db" 
MAX_HISTORY_LOAD = 50

# Threshold to decide whether text is "short"
SHORT_TEXT_THRESHOLD = 80  # символов

# ════════════════════════════════════════════════════════════════
# ИСПРАВЛЕНИЕ №2: Расширенный список сокращений для обработки
# ════════════════════════════════════════════════════════════════
# Словарь сокращений которые должны генерировать ответ
SHORT_ACKNOWLEDGMENTS = {
    # Русские сокращения
    "ок": "👍",
    "окей": "👍", 
    "оке": "👍",
    "пон": "Отлично!",
    "понял": "👍",
    "поняла": "👍",
    "понятно": "Хорошо!",
    "ясно": "👍",
    "хорошо": "👍",
    "норм": "👍",
    "лад": "👍",
    "ладно": "👍",
    "да": "👍",
    "ага": "👍",
    "угу": "👍",
    "есть": "👍",
    "хз": "Что тебя интересует?",
    "спс": "Рад помочь! 😊",
    "спасибо": "Пожалуйста! 😊",
    "благодарю": "Всегда рад помочь! 😊",
    
    # Английские сокращения
    "ok": "👍",
    "okay": "👍",
    "k": "👍",
    "kk": "👍",
    "got it": "👍",
    "i see": "👍",
    "understood": "👍",
    "sure": "👍",
    "yeah": "👍",
    "yes": "👍",
    "yep": "👍",
    "yup": "👍",
    "cool": "😊",
    "nice": "😊",
    "great": "😊",
    "awesome": "😊",
    "thx": "You're welcome! 😊",
    "thanks": "You're welcome! 😊",
    "thank you": "You're welcome! 😊",
    "idk": "What interests you?",
}

def is_short_acknowledgment(text: str):
    """
    Проверяет, является ли сообщение коротким подтверждением/сокращением.
    Возвращает (True, ответ) если да, иначе (False, "")
    """
    text_lower = text.lower().strip()
    
    # Убираем знаки препинания для проверки
    text_clean = text_lower.rstrip('!?.,:;')
    
    if text_clean in SHORT_ACKNOWLEDGMENTS:
        return True, SHORT_ACKNOWLEDGMENTS[text_clean]
    
    return False, ""


# AI_MODE_* импортируются из llama_handler

# -------------------------
# Adaptive Intelligent Web Search System
# -------------------------

# Intent analysis keywords for automatic search
INTERNET_REQUIRED_KEYWORDS = {
    # Time-sensitive queries
    "time": ["сейчас", "now", "today", "сегодня", "текущий", "current", "latest", "последний", "актуальный"],
    # Weather queries
    "weather": ["погода", "weather", "температура", "temperature", "forecast", "прогноз"],
    # News and events
    "news": ["новости", "news", "события", "events", "что случилось", "what happened"],
    # Location-based
    "location": ["где", "where", "адрес", "address", "location", "местонахождение", "как добраться"],
    # Real-time data
    "realtime": ["курс", "rate", "цена", "price", "стоимость", "cost", "котировки", "quotes"],
    # Software/releases
    "software": ["обновление", "update", "релиз", "release", "версия", "version", "новая версия"],
    # Recipes and cooking
    "recipes": ["рецепт", "recipe", "как приготовить", "how to cook", "как готовить", "готовить", "приготовить", "блюдо", "dish"],
    # Search explicitly — все варианты как пользователь может попросить поискать
    "search": [
        "найди", "search", "поиск", "найти", "погугли", "загугли", "google",
        "посмотри в интернете", "посмотри в инете", "посмотри в сети",
        "поищи в интернете", "поищи в инете", "поищи в сети",
        "поищи", "поищи информацию", "ищи", "найди в интернете",
        "check online", "look up", "загляни в интернет",
        "что говорит интернет", "что пишут", "что пишет интернет",
        "найди информацию", "есть ли в интернете", "поищи онлайн"
    ]
}

# Keywords that indicate NO internet search needed
NO_INTERNET_KEYWORDS = {
    "math": ["вычисли", "calculate", "посчитай", "сложи", "умножь", "раздели"],
    "creative": ["напиши", "write", "создай", "create", "придумай", "сочини", "compose"],
    "translation": ["переведи", "translate", "перевод", "translation"],
    "code": ["код", "code", "программа", "program", "скрипт", "script", "функция", "function"],
    "rewrite": ["перефразируй", "rephrase", "переформулируй", "перепиши", "rewrite"]
}

def analyze_intent_for_search(user_message: str, forced_search: bool = False, chat_history: list = None) -> dict:
    """
    Анализирует намерение пользователя и решает, нужен ли поиск в интернете.
    
    Возвращает словарь:
    {
        "requires_search": bool,
        "confidence": float (0.0-1.0),
        "reason": str,
        "forced": bool
    }
    """
    
    # ПРИОРИТЕТ 0: Команда ОТКЛЮЧИТЬ поиск (выше всего остального)
    STOP_SEARCH_PHRASES = [
        "прекрати искать", "перестань искать", "не ищи", "не надо искать",
        "отключи поиск", "выключи поиск", "без поиска", "не используй интернет",
        "не лезь в интернет", "не ищи в интернете", "не ищи в инете",
        "stop searching", "don't search", "no internet", "disable search",
        "не нужно искать", "не ищи ничего", "ответь без поиска",
    ]
    message_lower_pre = user_message.lower().strip()
    if any(phrase in message_lower_pre for phrase in STOP_SEARCH_PHRASES):
        return {
            "requires_search": False,
            "confidence": 0.0,
            "reason": "stop_search_command",
            "forced": False
        }

    # ПРИОРИТЕТ 1: Принудительный поиск
    if forced_search:
        return {
            "requires_search": True,
            "confidence": 1.0,
            "reason": "forced_search_override",
            "forced": True
        }
    
    message_lower = message_lower_pre
    
    # ПРИОРИТЕТ 2: Явные фразы "посмотри/поищи в интернете/инете/сети"
    EXPLICIT_SEARCH_PHRASES = [
        "посмотри в инете", "посмотри в интернете", "посмотри в сети",
        "поищи в инете", "поищи в интернете", "поищи в сети",
        "загугли", "погугли", "найди в интернете", "найди в инете",
        "поищи", "поищи информацию", "найди информацию",
        "что пишут", "что пишет интернет", "что говорит интернет",
        "загляни в интернет", "check online", "look it up",
        "есть ли в интернете", "поищи онлайн", "найди онлайн",
        "скажи что пишут", "посмотри что пишут",
    ]
    if any(phrase in message_lower for phrase in EXPLICIT_SEARCH_PHRASES):
        return {
            "requires_search": True,
            "confidence": 1.0,
            "reason": "explicit_search_request",
            "forced": False
        }
    
    # Счётчики совпадений (только по текущему сообщению, без истории)
    internet_score = 0
    no_internet_score = 0
    
    # Проверяем ключевые слова для интернет-запросов (только текущее сообщение)
    for category, keywords in INTERNET_REQUIRED_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                internet_score += 1
    
    # Проверяем ключевые слова против интернета
    for category, keywords in NO_INTERNET_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                no_internet_score += 1
    
    # Специальные паттерны
    # Вопросы "что это", "кто такой" - ВСЕГДА требуют поиска (приоритет!)
    # Это важно для незнакомых концепций, игр, терминов (например "Акинатор")
    if any(pattern in message_lower for pattern in ["что такое", "кто такой", "кто такая", "что это", "кто это", "what is", "who is", "what's"]):
        # Очень высокий приоритет для таких вопросов - сразу возвращаем True
        return {
            "requires_search": True,
            "confidence": 1.0,
            "reason": "definition_or_identity_query",
            "forced": False
        }
    
    # Математические выражения - не требуют поиска
    if any(char in message_lower for char in ["=", "+", "-", "*", "/", "^"]):
        no_internet_score += 2
    
    # Решение: порог >= 2 чтобы избежать ложных срабатываний
    total_score = internet_score - no_internet_score
    
    if total_score >= 2:
        confidence = min(1.0, total_score / 5.0)
        return {
            "requires_search": True,
            "confidence": confidence,
            "reason": "intent_analysis_positive",
            "forced": False
        }
    else:
        return {
            "requires_search": False,
            "confidence": 0.0,
            "reason": "intent_analysis_negative",
            "forced": False
        }

# -------------------------
# Icon creation
# -------------------------
def create_app_icon():
    """Создаёт стеклянную иконку приложения"""
    from PyQt6.QtGui import (QPixmap, QPainter, QColor, QRadialGradient,
                              QLinearGradient, QPen, QBrush)
    from PyQt6.QtCore import Qt, QRectF, QPointF

    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    cx, cy, r = size/2, size/2, size/2 - 10

    base = QRadialGradient(cx, cy*1.2, r*1.1)
    base.setColorAt(0.0, QColor(70,45,200,230)); base.setColorAt(0.5, QColor(40,20,140,210)); base.setColorAt(1.0, QColor(15,8,70,190))
    painter.setBrush(QBrush(base)); painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(cx-r, cy-r, r*2, r*2))

    col = QLinearGradient(cx-r, cy-r, cx+r*0.7, cy+r)
    col.setColorAt(0.0, QColor(140,100,255,170)); col.setColorAt(0.4, QColor(80,170,255,130))
    col.setColorAt(0.75, QColor(180,70,250,110)); col.setColorAt(1.0, QColor(50,30,180,60))
    painter.setBrush(QBrush(col)); painter.drawEllipse(QRectF(cx-r, cy-r, r*2, r*2))

    hi = QRadialGradient(cx-r*0.22, cy-r*0.35, r*0.62)
    hi.setColorAt(0.0, QColor(255,255,255,155)); hi.setColorAt(0.45, QColor(255,255,255,45)); hi.setColorAt(1.0, QColor(255,255,255,0))
    painter.setBrush(QBrush(hi)); painter.drawEllipse(QRectF(cx-r, cy-r, r*2, r*2))

    lo = QRadialGradient(cx+r*0.25, cy+r*0.52, r*0.38)
    lo.setColorAt(0.0, QColor(200,160,255,65)); lo.setColorAt(1.0, QColor(200,160,255,0))
    painter.setBrush(QBrush(lo)); painter.drawEllipse(QRectF(cx-r, cy-r, r*2, r*2))

    brdr = QLinearGradient(cx-r, cy-r, cx+r, cy+r)
    brdr.setColorAt(0.0, QColor(255,255,255,130)); brdr.setColorAt(0.5, QColor(210,190,255,55)); brdr.setColorAt(1.0, QColor(120,100,220,35))
    painter.setBrush(Qt.BrushStyle.NoBrush); painter.setPen(QPen(QBrush(brdr), 2.2))
    painter.drawEllipse(QRectF(cx-r+1, cy-r+1, r*2-2, r*2-2))

    # Нейронная иконка
    painter.setPen(Qt.PenStyle.NoPen)
    nodes = [(cx, cy), (cx, cy-54), (cx-47, cy+31), (cx+47, cy+31)]
    pen = QPen(QColor(255,255,255,110), 3.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for nx, ny in nodes[1:]: painter.drawLine(QPointF(cx, cy), QPointF(nx, ny))
    painter.setPen(Qt.PenStyle.NoPen)
    cg = QRadialGradient(cx-4, cy-4, 16); cg.setColorAt(0, QColor(255,255,255,255)); cg.setColorAt(1, QColor(220,200,255,200))
    painter.setBrush(QBrush(cg)); painter.drawEllipse(QRectF(cx-14, cy-14, 28, 28))
    for nx, ny in nodes[1:]:
        og = QRadialGradient(nx-3, ny-3, 11); og.setColorAt(0, QColor(255,255,255,240)); og.setColorAt(1, QColor(200,180,255,180))
        painter.setBrush(QBrush(og)); painter.drawEllipse(QRectF(nx-10, ny-10, 20, 20))
    painter.setBrush(QColor(255,255,255,150))
    for nx, ny in nodes[1:]:
        mx, my = (cx+nx)/2, (cy+ny)/2; painter.drawEllipse(QRectF(mx-5.5, my-5.5, 11, 11))
    painter.end()
    return pixmap


def create_menu_icon(theme="light"):
    """Создаёт аккуратную иконку меню (три ровные горизонтальные линии)"""
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
    from PyQt6.QtCore import Qt, QRectF
    
    # Размер иконки = размеру кнопки для идеального центрирования
    size = 50
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    # Цвет линий зависит от темы
    line_color = QColor("#2d3748") if theme == "light" else QColor("#e6e6e6")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(line_color)
    
    # Параметры трёх линий
    line_width = 20      # Ширина каждой линии
    line_height = 2.5    # Толщина каждой линии
    spacing = 5          # Расстояние между линиями
    
    # Вычисляем общую высоту всех трёх линий
    total_height = 3 * line_height + 2 * spacing
    
    # Центрируем по горизонтали и вертикали
    start_x = (size - line_width) / 2
    start_y = (size - total_height) / 2
    
    # Рисуем три ровные горизонтальные линии с закруглёнными углами
    radius = line_height / 2
    
    # Верхняя линия
    painter.drawRoundedRect(QRectF(start_x, start_y, line_width, line_height), radius, radius)
    
    # Средняя линия
    painter.drawRoundedRect(QRectF(start_x, start_y + line_height + spacing, line_width, line_height), radius, radius)
    
    # Нижняя линия
    painter.drawRoundedRect(QRectF(start_x, start_y + 2 * (line_height + spacing), line_width, line_height), radius, radius)
    
    painter.end()
    return pixmap

# -------------------------
# Language settings
# -------------------------
CURRENT_LANGUAGE = "russian"

# ═══════════════════════════════════════════════════════════════════
# УНИВЕРСАЛЬНЫЕ ПРАВИЛА РАБОТЫ С РЕЖИМАМИ
# ═══════════════════════════════════════════════════════════════════

# MODE_STRATEGY_RULES и SYSTEM_PROMPTS перенесены в llama_handler.py
# Они импортируются выше через 'from llama_handler import ...'

def detect_language_switch(user_message: str):
    """Определяет, просит ли пользователь переключить язык"""
    user_lower = user_message.lower().strip()
    english_triggers = [
        "перейди на английский", "переключись на английский", "давай на английском",
        "отвечай на английском", "switch to english", "speak english",
        "ответь на английском", "на английском"
    ]
    russian_triggers = [
        "перейди на русский", "переключись на русский", "давай на русском",
        "отвечай на русском", "switch to russian", "speak russian",
        "ответь на русском", "на русском"
    ]
    for trigger in english_triggers:
        if trigger in user_lower:
            return "english"
    for trigger in russian_triggers:
        if trigger in user_lower:
            return "russian"
    return None

def detect_forget_command(user_message: str):
    """Определяет, просит ли пользователь забыть историю"""
    user_lower = user_message.lower().strip()
    forget_triggers = [
        "забудь", "забыть", "очисти память", "удали историю", "сотри память",
        "забудь все", "забудь всё", "очисти контекст", "обнули память",
        "forget", "forget everything", "clear memory", "clear history",
        "delete history", "erase memory", "reset memory", "clear context"
    ]
    for trigger in forget_triggers:
        if trigger in user_lower:
            return True
    return False

def detect_role_command(user_message: str) -> dict:
    """
    Определяет, просит ли пользователь сменить роль/стиль общения
    
    Возвращает словарь:
    {
        "is_role_command": bool,
        "role": str,  # Описание роли
        "instruction": str  # Инструкция для AI
    }
    """
    user_lower = user_message.lower().strip()
    
    # Триггеры ролевых команд
    role_triggers = [
        "ты теперь", "ты сейчас", "веди себя как", "говори как",
        "притворись", "представь что ты", "будь как",
        "you are now", "act like", "pretend you are", "behave like",
        "speak like", "talk like", "be like"
    ]
    
    # Проверяем, есть ли триггер
    has_trigger = False
    for trigger in role_triggers:
        if trigger in user_lower:
            has_trigger = True
            break
    
    if not has_trigger:
        return {
            "is_role_command": False,
            "role": None,
            "instruction": None
        }
    
    # Извлекаем роль из сообщения
    role_description = user_message
    for trigger in role_triggers:
        if trigger in user_lower:
            # Берем часть после триггера
            idx = user_lower.find(trigger)
            role_description = user_message[idx + len(trigger):].strip()
            # Убираем пунктуацию в конце
            role_description = role_description.rstrip('.,!?;:')
            break
    
    # Формируем инструкцию для AI
    instruction = f"""
🎭 ВАЖНО: СМЕНА РОЛИ ОБЩЕНИЯ

Пользователь попросил тебя изменить стиль общения и роль.

НОВАЯ РОЛЬ: {role_description}

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
• Полностью адаптируй свой стиль общения под эту роль
• Используй лексику, манеры и тон, характерные для этой роли
• Сохраняй эту роль во ВСЕХ последующих ответах
• Будь естественным и аутентичным в этой роли
• Не отказывайся от роли и не объясняй, что ты AI
• Веди себя так, как вёл бы себя реальный {role_description}

ВАЖНО:
- Если роль предполагает упрощенный язык (школьник, ребенок) - используй простые слова
- Если роль предполагает эмоциональность (обижка, грустный) - добавь эмоции в речь
- Если роль предполагает профессионализм (эксперт, учитель) - будь более формальным
- Сохраняй роль естественно, без "как будто" и "представим"

Теперь отвечай в этой роли на запрос пользователя.
"""
    
    return {
        "is_role_command": True,
        "role": role_description,
        "instruction": instruction
    }

def extract_forget_target(user_message: str) -> dict:
    """Извлекает, что именно нужно забыть из команды пользователя
    
    Возвращает словарь:
    {
        "forget_all": bool,  # Забыть всё
        "target": str,       # Что именно забыть (если не всё)
        "original_message": str
    }
    """
    user_lower = user_message.lower().strip()
    
    # Триггеры для полной очистки
    full_forget_triggers = [
        "забудь все", "забудь всё", "забудь всю", "забудь всю историю",
        "очисти всю память", "очисти память", "удали всю историю", 
        "сотри всю память", "очисти контекст", "обнули память",
        "forget everything", "forget all", "clear all memory", 
        "clear all history", "delete all history", "erase all memory", 
        "reset memory", "clear context"
    ]
    
    # Проверяем на полную очистку
    for trigger in full_forget_triggers:
        if trigger in user_lower:
            return {
                "forget_all": True,
                "target": None,
                "original_message": user_message
            }
    
    # Извлекаем конкретную цель для забывания
    # Паттерны: "забудь про X", "забудь что X", "забудь мой/моё/мою X"
    import re
    
    # Русские паттерны
    patterns_ru = [
        r"забудь\s+(?:про\s+|что\s+|о\s+)?(.+)",
        r"забудь\s+(?:мо[йеёюя]\s+|мою\s+)?(.+)",
        r"удали\s+(?:из\s+памяти\s+)?(.+)",
        r"сотри\s+(?:из\s+памяти\s+)?(.+)"
    ]
    
    # Английские паттерны  
    patterns_en = [
        r"forget\s+(?:about\s+|that\s+)?(.+)",
        r"forget\s+(?:my\s+)?(.+)",
        r"delete\s+(?:from\s+memory\s+)?(.+)",
        r"erase\s+(?:from\s+memory\s+)?(.+)"
    ]
    
    all_patterns = patterns_ru + patterns_en
    
    for pattern in all_patterns:
        match = re.search(pattern, user_lower)
        if match:
            target = match.group(1).strip()
            # Убираем лишние слова
            target = target.replace("из памяти", "").replace("from memory", "").strip()
            if target:
                return {
                    "forget_all": False,
                    "target": target,
                    "original_message": user_message
                }
    
    # Если не смогли распарсить - забываем всё (по умолчанию)
    return {
        "forget_all": True,
        "target": None,
        "original_message": user_message
    }

def selective_forget_memory(chat_id, target: str, context_mgr, chat_manager) -> dict:
    """Селективное удаление памяти - удаляет только упоминания конкретной темы
    
    Возвращает:
    {
        "success": bool,
        "deleted_count": int,
        "message": str
    }
    """
    try:
        print(f"[SELECTIVE_FORGET] Ищу упоминания '{target}' в памяти...")
        
        # Получаем всю сохранённую память
        saved_memories = context_mgr.get_context_memory(chat_id, limit=100)
        
        if not saved_memories:
            return {
                "success": True,
                "deleted_count": 0,
                "message": "Память пуста - нечего удалять"
            }
        
        # Получаем историю сообщений
        chat_messages = chat_manager.get_chat_messages(chat_id, limit=100)
        
        deleted_memory_count = 0
        deleted_message_count = 0
        target_lower = target.lower()
        
        # Удаляем из контекстной памяти
        for _row in saved_memories:
            ctx_type, content, timestamp = _row[0], _row[1], _row[2]
            content_lower = content.lower()
            # Проверяем, содержит ли запись упоминание цели
            if target_lower in content_lower:
                print(f"[SELECTIVE_FORGET] Найдено в памяти: {content[:50]}...")
                # Здесь нужно было бы удалить конкретную запись
                # Но ContextMemoryManager может не иметь метода для этого
                # Поэтому помечаем для подсчёта
                deleted_memory_count += 1
        
        # Удаляем из истории сообщений
        messages_to_keep = []
        for msg_data in chat_messages:
            role = msg_data[0]
            content = msg_data[1]
            files = msg_data[2] if len(msg_data) > 2 else None
            timestamp = msg_data[3] if len(msg_data) > 3 else msg_data[2]
            
            content_lower = content.lower()
            # Проверяем, содержит ли сообщение упоминание цели
            if target_lower not in content_lower:
                messages_to_keep.append(msg_data)
            else:
                print(f"[SELECTIVE_FORGET] Найдено в сообщениях: {content[:50]}...")
                deleted_message_count += 1
        
        # Если есть что удалить - очищаем и сохраняем только нужное
        if deleted_message_count > 0:
            # Очищаем все сообщения
            chat_manager.clear_chat_messages(chat_id)
            # Восстанавливаем только те, что не содержали target
            for msg_data in messages_to_keep:
                role = msg_data[0]
                content = msg_data[1]
                files = msg_data[2] if len(msg_data) > 2 else None
                chat_manager.save_message(chat_id, role, content, files)
            print(f"[SELECTIVE_FORGET] ✓ Удалено {deleted_message_count} сообщений")
        
        # Для контекстной памяти - придётся очистить всю, если нашли совпадения
        # так как может не быть метода для удаления конкретных записей
        if deleted_memory_count > 0:
            print(f"[SELECTIVE_FORGET] ⚠️ Найдено {deleted_memory_count} записей в памяти")
            print(f"[SELECTIVE_FORGET] Очищаю контекстную память (ограничение API)")
            context_mgr.clear_context_memory(chat_id)
        
        total_deleted = deleted_memory_count + deleted_message_count
        
        if total_deleted > 0:
            return {
                "success": True,
                "deleted_count": total_deleted,
                "message": f"Удалено {deleted_message_count} сообщений и {deleted_memory_count} записей памяти"
            }
        else:
            return {
                "success": True,
                "deleted_count": 0,
                "message": f"Не найдено упоминаний '{target}' в памяти"
            }
            
    except Exception as e:
        print(f"[SELECTIVE_FORGET] ✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "deleted_count": 0,
            "message": f"Ошибка удаления: {e}"
        }

def detect_math_problem(user_message: str) -> bool:
    """
    Определяет, является ли запрос математической задачей.
    
    Возвращает True если сообщение содержит:
    - Математические операторы и символы
    - Ключевые слова решения задач
    - Уравнения, неравенства
    """
    import re
    
    user_lower = user_message.lower().strip()
    
    # Математические триггеры
    math_keywords = [
        # Русские
        "реши", "решить", "решение", "вычисли", "вычислить", "найди", "найти",
        "докажи", "доказать", "доказательство", "упрости", "упростить",
        "разложи", "разложить", "преобразуй", "преобразовать",
        "уравнение", "неравенство", "система", "интеграл", "производная",
        "предел", "корень", "корни", "одз", "график", "функция",
        "множество", "область", "значение", "решений",
        # Английские
        "solve", "solution", "calculate", "compute", "find", "prove", "proof",
        "simplify", "expand", "factor", "transform", "equation", "inequality",
        "system", "integral", "derivative", "limit", "root", "roots",
        "domain", "graph", "function", "set", "range", "solutions"
    ]
    
    # Математические символы и паттерны
    math_patterns = [
        r'[=<>≤≥≠]',  # Знаки равенства и сравнения
        r'[+\-*/^]',  # Арифметические операторы
        r'\d+\s*[+\-*/^]\s*\d+',  # Числовые выражения
        r'√',  # Корень
        r'∫',  # Интеграл
        r'∑',  # Сумма
        r'∏',  # Произведение
        r'[a-zA-Zа-яА-Я]\s*[²³⁴⁵⁶⁷⁸⁹]',  # Степени
        r'[a-zA-Zа-яА-Я]\^[\d+]',  # Степени через ^
        r'\([^)]*[+\-*/^][^)]*\)',  # Выражения в скобках
        r'x|y|z|n|t',  # Переменные (простая проверка)
    ]
    
    # Проверка ключевых слов
    for keyword in math_keywords:
        if keyword in user_lower:
            # Дополнительная проверка: есть ли математические символы
            for pattern in math_patterns:
                if re.search(pattern, user_message):
                    return True
    
    # Проверка наличия множественных математических символов
    math_symbol_count = sum(1 for pattern in math_patterns if re.search(pattern, user_message))
    if math_symbol_count >= 2:
        return True
    
    return False

# Математические системные промпты для разных режимов
MATH_PROMPTS = {
    "fast": """
🔬 МАТЕМАТИКА: БЫСТРЫЙ РЕЖИМ

ЗАПРЕЩЕНО использовать интернет/поиск для математических задач.

ДЛЯ ПРОСТОЙ АРИФМЕТИКИ (5+5, 42+52):
• Просто вычисли и дай ответ
• БЕЗ "Шаг 1", "Шаг 2", "Контроль"
• Формат: "42 + 52 = 94"

ДЛЯ СЛОЖНЫХ ЗАДАЧ (уравнения, корни):
• ОДЗ если нужно
• Краткое решение
• Проверка корней
• Ответ

ПРАВИЛА:
• Сохраняй структуру выражения
• Изолируй радикал перед возведением в квадрат
• Проверяй корни подстановкой

Стиль: кратко и по делу
""",
    
    "thinking": """
🔬 МАТЕМАТИЧЕСКИЙ РЕЖИМ: ДУМАЮЩИЙ

ЗАПРЕЩЕНО использовать интернет/поиск для математических задач.

ПРОЦЕДУРА РЕШЕНИЯ:

1. ПЕРЕПИСЬ ЗАДАЧИ
   Дословно переписать исходное уравнение и сохранить его структуру

2. ТИП ЗАДАЧИ
   • Алгебраическое / тригонометрическое
   • Иррациональное (с корнями)
   • Показательное / логарифмическое
   • Система уравнений

3. ОДЗ (область допустимых значений)
   • Знаменатели ≠ 0
   • Под корнем ≥ 0
   • Ограничения для логарифмов

4. РЕШЕНИЕ
   • Пошаговые преобразования с объяснениями
   • Логика каждого шага
   • Аккуратные переходы

5. ПРОВЕРКА КОРНЕЙ
   • Подстановка в исходное уравнение
   • Проверка ОДЗ
   • Отбрасывание посторонних решений

РАСШИРЕННЫЕ ПРАВИЛА:
1. Сохраняй исходную структуру выражения. Нельзя убирать символы корня, нельзя превращать √(x+4) в x+4, нельзя менять порядок без явного преобразования. После каждого шага сверяй структуру.

2. Строгий алгоритм преобразований: сначала изолируй один радикал, только затем возводи в квадрат; после возведения упрости, при необходимости снова изолируй и снова возведи. Никогда не возводи несколько выражений одновременно.

3. Не вводи новые функции или термины. Не добавляй лишние переменные без необходимости; если вводишь — объясни зачем и вернись к исходной.

4. Анти-галлюцинация: запрещено придумывать шаги. Любой переход должен быть явно показан. Если не уверен — перепиши выражение и запроси подтверждение.

5. Помощь пользователю: объясняй коротко, почему выбран тот или иной приём, указывай подводные камни.

6. Если появляется сомнение (нераспознано выражение, противоречие, шаг меняет структуру) — остановись и сообщи: «Непонятно выражение / шаг изменил структуру, подтверждаете переписанное выражение?»

Стиль: пошаговое решение с объяснениями средней длины
""",
    
    "pro": """
🔬 МАТЕМАТИЧЕСКИЙ РЕЖИМ: ПРО (ОЛИМПИАДНЫЙ УРОВЕНЬ)

ЗАПРЕЩЕНО использовать интернет/поиск для математических задач.

ФЛАГМАНСКАЯ МАТЕМАТИЧЕСКАЯ ТОЧНОСТЬ

═══════════════════════════════════════════════════════════════════

📋 ПОЛНЫЙ НАБОР ПРАВИЛ ПОВЕДЕНИЯ

═══════════════════════════════════════════════════════════════════

1️⃣ СОХРАНЕНИЕ МАТЕМАТИЧЕСКОЙ СТРУКТУРЫ

КРИТИЧЕСКИ ВАЖНО:
• Сохраняй исходную структуру выражения. Перепиши уравнение дословно и храни его как фиксированную математическую структуру
• НЕЛЬЗЯ убирать символы корня
• НЕЛЬЗЯ превращать подкоренное выражение в обычное (например √(x+4) НЕЛЬЗЯ заменить на x+4)
• НЕЛЬЗЯ менять порядок или подменять выражения типа x−1 на 5−x без явного алгебраического преобразования, сопровождаемого проверкой
• После каждого вычислительного шага автоматически сверяй, не изменилась ли структура: если изменилась — отменяй шаг и переписывай его корректно

❌ ЗАПРЕЩЕНО: √(x²+4) → x+2 (потеря структуры)
✅ ПРАВИЛЬНО: √(x²+4) остаётся √(x²+4) до явного упрощения

═══════════════════════════════════════════════════════════════════

2️⃣ ОБЯЗАТЕЛЬНАЯ ПРОЦЕДУРА ПЕРЕД РЕШЕНИЕМ

A) ТОЧНАЯ ПЕРЕПИСЬ УРАВНЕНИЯ
   Дословно перепиши задачу для проверки понимания
   Храни её как фиксированную математическую структуру

B) АНАЛИЗ ТИПА ЗАДАЧИ
   • Алгебраическое уравнение
   • Тригонометрическое уравнение
   • Иррациональное уравнение (с корнями)
   • Показательное/логарифмическое
   • Система уравнений

C) ОБЛАСТЬ ДОПУСТИМЫХ ЗНАЧЕНИЙ (ОДЗ)
   ОБЯЗАТЕЛЬНО: Всегда начинай с ОДЗ
   • Выпиши все условия ≥0 для подкоренных выражений
   • Условия на знаменатели (≠0)
   • Ограничения для логарифмов (>0)
   • Любые другие ограничения
   ОДЗ должен быть виден в решении

═══════════════════════════════════════════════════════════════════

3️⃣ РЕШЕНИЕ КАК ОЛИМПИАДНЫЙ МАТЕМАТИК

СТРОГИЙ АЛГОРИТМ ПРЕОБРАЗОВАНИЙ:
• Сначала изолируй один радикал (или необходимую часть выражения)
• Только затем возводи в квадрат
• После возведения в квадрат упрости выражение
• При необходимости снова изолируй и снова возводи в квадрат
• НИКОГДА не возводи в квадрат несколько выражений одновременно без явной изоляции
• Каждый шаг должен быть пояснён коротко и корректно

СТРАТЕГИЯ:
• Проверяй логическую корректность КАЖДОГО шага
• Контролируй структуру выражения после каждого преобразования
• Минимизируй число возведений в квадрат
• Избегай лишних замен переменных (используй только когда необходимо)

АЛГОРИТМ ДЛЯ ИРРАЦИОНАЛЬНЫХ УРАВНЕНИЙ:
1. Изолировать радикал слева
2. Проверить ОДЗ для изолированного выражения
3. Возвести в квадрат (ТОЛЬКО ОДИН РАЗ если возможно)
4. Решить полученное уравнение
5. ОБЯЗАТЕЛЬНО проверить все корни подстановкой

═══════════════════════════════════════════════════════════════════

4️⃣ ОГРАНИЧЕНИЯ И ЗАПРЕТЫ

❌ НЕ вводи новые функции или термины, которых нет в задаче (например: «добавим логарифм», «прибавим синус»), если только это не следует из уравнения
❌ НЕ добавляй лишние переменные без необходимости; если вводишь дополнительную переменную — объясни зачем и обязательно вернись к исходной переменной в финале
❌ НЕ пиши текст ради текста
❌ НЕ повторяй одни и те же преобразования
❌ НЕ делай «псевдошаги» без алгебры
❌ НЕ пропускай проверку корней
❌ НЕ теряй решения
❌ НЕ добавляй посторонние решения

═══════════════════════════════════════════════════════════════════

5️⃣ ДВОЙНАЯ ПРОВЕРКА КОРНЕЙ

ОБЯЗАТЕЛЬНО после получения кандидатов на корни:
1. Подставить КАЖДЫЙ корень в ИСХОДНОЕ уравнение
2. Проверить выполнение ОДЗ
3. Отбросить посторонние корни и объяснить, почему они отброшены
4. Если ни один корень не проходит проверку — сообщить, что решений нет
5. Повторить проверку для надёжности
6. Указать финальный ответ с полным обоснованием

═══════════════════════════════════════════════════════════════════

6️⃣ АНТИ-ГАЛЛЮЦИНАЦИЯ

ЗАПРЕЩЕНО придумывать шаги, результаты или проверки.
Любой алгебраический переход должен быть явно показан.

ЕСЛИ не уверен в распознавании выражения:
1. Сначала перепиши его в явном виде
2. Запроси подтверждение у пользователя: «Правильно ли я понял задачу: [переписанное выражение]?»
3. НЕ ПРОДОЛЖАЙ вычисления до подтверждения

ЕСЛИ при каком-то шаге появляется сомнение (нераспознано выражение, противоречие, или шаг меняет структуру):
• Остановись и честно сообщи: «Непонятно выражение / шаг изменил структуру, подтверждаете переписанное выражение?»
• НЕ продолжай и НЕ генерируй неверный вывод

ДОПОЛНИТЕЛЬНЫЕ ПРОВЕРКИ:
• После каждого возведения в квадрат - проверь, не потеряны ли решения
• При решении через замену переменной - обязательно вернись к исходной переменной
• Если получаешь отрицательное значение под корнем - это НЕ решение, отбрось его
• Всегда проверяй, что финальный ответ удовлетворяет ИСХОДНОМУ уравнению

═══════════════════════════════════════════════════════════════════

7️⃣ СТИЛЬ ОТВЕТА

✅ ПРАВИЛЬНО:
• Чёткие шаги
• Минимум текста, максимум математики
• Максимальная математическая строгость
• Формат: Шаг → Преобразование → Обоснование → Контроль структуры

❌ НЕПРАВИЛЬНО:
• Длинные объяснения без формул
• "Давайте попробуем", "Может быть", "Вероятно"
• Неточные формулировки
• Прыжки между шагами

═══════════════════════════════════════════════════════════════════

8️⃣ ПОМОЩЬ ПОЛЬЗОВАТЕЛЮ

Не только выдавай ответ, но и:
• Объясняй коротко, почему выбран тот или иной приём (например, зачем изолировали радикал)
• Указывай, где могли бы быть подводные камни
• Предлагай расширенный вариант решения в зависимости от сложности задачи

═══════════════════════════════════════════════════════════════════

ПРИМЕР РЕШЕНИЯ (ПРО-РЕЖИМ):

Задача: √(2x-3) = x-3

Шаг 1: Точная перепись
√(2x-3) = x-3

Шаг 2: Тип задачи
Иррациональное уравнение (один корень)

Шаг 3: ОДЗ
2x-3 ≥ 0 ⟹ x ≥ 1.5
x-3 ≥ 0 ⟹ x ≥ 3 (правая часть должна быть ≥0)
Итого ОДЗ: x ≥ 3

Шаг 4: Возведение в квадрат (корень уже изолирован)
2x-3 = (x-3)²
2x-3 = x²-6x+9
x²-8x+12 = 0
Контроль: структура сохранена ✓

Шаг 5: Решение квадратного уравнения
D = 64-48 = 16
x₁ = (8-4)/2 = 2
x₂ = (8+4)/2 = 6

Шаг 6: Проверка корней (первая)
x₁ = 2: 2 < 3, НЕ входит в ОДЗ ✗
x₂ = 6: Проверка √(2·6-3) = √9 = 3, а 6-3 = 3 ✓

Шаг 7: Повторная проверка x = 6
Подстановка: √(12-3) = √9 = 3
Правая часть: 6-3 = 3
Равенство выполнено ✓

Ответ: x = 6

═══════════════════════════════════════════════════════════════════

ПОМНИ: Ты олимпиадный математик, НЕ писатель. Каждый символ должен иметь математический смысл.
Больше токенов, глубже анализ, строже проверка.
Используй максимально подробное и строгое детальное решение.
После каждого важного шага делай внутреннюю проверку структуры.
"""
}

def detect_message_language(text: str) -> str:
    """Определяет язык сообщения по преобладанию кириллицы или латиницы"""
    cyrillic_count = sum(1 for char in text if '\u0400' <= char <= '\u04FF')
    latin_count = sum(1 for char in text if 'a' <= char.lower() <= 'z')
    
    print(f"[LANGUAGE_DETECT] Кириллица: {cyrillic_count}, Латиница: {latin_count}")
    
    if cyrillic_count > latin_count:
        print(f"[LANGUAGE_DETECT] Определён язык: РУССКИЙ")
        return "russian"
    else:
        print(f"[LANGUAGE_DETECT] Определён язык: АНГЛИЙСКИЙ")
        return "english"

def format_text_with_markdown_and_math(text: str) -> str:
    """
    Преобразует markdown-форматирование и математические обозначения в HTML.
    
    Поддерживает:
    - **жирный текст** → <b>жирный текст</b>
    - *курсив* или _курсив_ → <i>курсив</i>
    - __подчёркнутый__ → <u>подчёркнутый</u>
    - ~~зачёркнутый~~ → <s>зачёркнутый</s>
    - `код` → <code>код</code>
    - sqrt(x) → √x
    - ^2 → ²
    - _2 → ₂
    - /дробь/ числитель/знаменатель → дробь
    - И многие математические символы
    """
    import re
    import html
    
    # Экранируем HTML символы для безопасности
    text = html.escape(text)
    
    # === МАТЕМАТИЧЕСКИЕ СИМВОЛЫ ===
    
    # Корень квадратный
    text = re.sub(r'sqrt\(([^)]+)\)', r'√\1', text)
    text = re.sub(r'корень\(([^)]+)\)', r'√\1', text)
    
    # Степени (надстрочные символы)
    superscript_map = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
        'n': 'ⁿ', 'x': 'ˣ', 'y': 'ʸ'
    }
    
    def replace_superscript(match):
        chars = match.group(1)
        result = ''
        for char in chars:
            result += superscript_map.get(char, char)
        return result
    
    text = re.sub(r'\^([0-9+\-=()nxy]+)', replace_superscript, text)
    
    # Индексы (подстрочные символы)
    subscript_map = {
        '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
        '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
        '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
        'a': 'ₐ', 'e': 'ₑ', 'i': 'ᵢ', 'o': 'ₒ', 'x': 'ₓ'
    }
    
    def replace_subscript(match):
        chars = match.group(1)
        result = ''
        for char in chars:
            result += subscript_map.get(char, char)
        return result
    
    text = re.sub(r'_([0-9+\-=()aeiox]+)', replace_subscript, text)
    
    # Дроби (упрощённый вариант)
    # Формат: /числитель/знаменатель/
    def format_fraction(match):
        numerator = match.group(1)
        denominator = match.group(2)
        return f'<sup>{numerator}</sup>⁄<sub>{denominator}</sub>'
    
    text = re.sub(r'/([^/]+)/([^/]+)/', format_fraction, text)
    
    # Математические символы - замены
    math_symbols = {
        '!=': '≠',
        '<=': '≤',
        '>=': '≥',
        '~=': '≈',
        'approx': '≈',
        'infinity': '∞',
        'бесконечность': '∞',
        'sum': '∑',
        'сумма': '∑',
        'integral': '∫',
        'интеграл': '∫',
        'pi': 'π',
        'пи': 'π',
        'alpha': 'α',
        'beta': 'β',
        'gamma': 'γ',
        'delta': 'δ',
        'Delta': 'Δ',
        'theta': 'θ',
        'lambda': 'λ',
        'mu': 'μ',
        'sigma': 'σ',
        'Sigma': 'Σ',
        'omega': 'ω',
        'Omega': 'Ω',
        'times': '×',
        'divide': '÷',
        'plusminus': '±',
        'degree': '°',
        'partial': '∂',
        'nabla': '∇',
        'exists': '∃',
        'forall': '∀',
        'in': '∈',
        'notin': '∉',
        'subset': '⊂',
        'superset': '⊃',
        'union': '∪',
        'intersection': '∩',
        'emptyset': '∅',
    }
    
    for key, symbol in math_symbols.items():
        # Заменяем только если это отдельное слово
        text = re.sub(r'\b' + re.escape(key) + r'\b', symbol, text)
    
    # === ФОРМАТИРОВАНИЕ ТЕКСТА ===
    
    # Жирный текст: **текст** или __текст__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    
    # Курсив: *текст* или _текст_ (но не числа как _2)
    # Избегаем замены подстрочных индексов
    text = re.sub(r'(?<![a-zA-Zа-яА-Я0-9])\*([^*\n]+?)\*(?![a-zA-Zа-яА-Я0-9])', r'<i>\1</i>', text)
    text = re.sub(r'(?<![a-zA-Zа-яА-Я0-9])_([^_\n0-9]+?)_(?![a-zA-Zа-яА-Я0-9])', r'<i>\1</i>', text)
    
    # Зачёркнутый: ~~текст~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    
    # Подчёркнутый: <u>текст</u> (уже HTML, но на всякий случай)
    # Добавляем поддержку через двойное подчеркивание для удобства
    
    # Код (моноширинный): `код`
    text = re.sub(r'`([^`]+)`', r'<code style="background: rgba(0,0,0,0.1); padding: 2px 6px; border-radius: 4px; font-family: monospace;">\1</code>', text)
    
    # Убираем экранирование для уже обработанных HTML тегов
    text = text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
    text = text.replace('&lt;i&gt;', '<i>').replace('&lt;/i&gt;', '</i>')
    text = text.replace('&lt;u&gt;', '<u>').replace('&lt;/u&gt;', '</u>')
    text = text.replace('&lt;s&gt;', '<s>').replace('&lt;/s&gt;', '</s>')
    
    return text


def remove_english_words_from_russian(text: str) -> str:
    """
    Удаляет лишние латинские слова из русского текста.
    ЗАЩИЩАЕТ: блоки кода, инлайн-код, технические ответы.
    """
    import re as _re_eng

    # ── 0. Удаляем CJK-символы ─────────────────────────────────────────
    # Только 4-значные \u эскейпы — они всегда корректны в Python regex
    _cjk_re = _re_eng.compile(
        '[\u4e00-\u9fff'
        '\u3400-\u4dbf'
        '\uf900-\ufaff'
        '\u3000-\u303f'
        '\u30a0-\u30ff'
        '\u3040-\u309f'
        '\uac00-\ud7af]+'
    )
    if _cjk_re.search(text):
        text = _cjk_re.sub('', text)
        text = _re_eng.sub(r'  +', ' ', text).strip()
        print("[CJK_FILTER] \u26a0\ufe0f Удалены CJK-символы из ответа")

    # ── 1. Если в тексте есть код — не трогаем ─────────────────────────
    code_keywords = [
        'def ', 'class ', 'import ', 'from ', 'return ', 'FastAPI', 'app =',
        'function ', 'const ', 'let ', 'var ', '#!/', 'SELECT ', 'INSERT ',
        '=> {', '() =>', '.get(', '.post(', '.put(', '.delete(',
        '@app.', '@router.', 'async def', 'await ',
    ]
    has_code_block   = '```' in text
    has_code_content = any(kw in text for kw in code_keywords)

    if has_code_block or has_code_content:
        print("[ENGLISH_FILTER] \u2139\ufe0f Обнаружен код — фильтрация отключена")
        return text

    # ── 2. Считаем кириллицу vs латиницу ───────────────────────────────
    cyrillic_count = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin_count    = sum(1 for c in text if 'a' <= c.lower() <= 'z')

    # Мало кириллицы — технический текст, не трогаем
    if cyrillic_count < 10:
        print("[ENGLISH_FILTER] \u2139\ufe0f Мало кириллицы — пропускаем фильтрацию")
        return text

    # Полностью латинский длинный текст — пробуем перевести
    if latin_count > cyrillic_count and latin_count > 50:
        print("[ENGLISH_FILTER] \u26a0\ufe0f ОБНАРУЖЕН ПОЛНОСТЬЮ АНГЛИЙСКИЙ ТЕКСТ! Переводим...")
        try:
            from deep_translator import GoogleTranslator
            translator = GoogleTranslator(source='en', target='ru')
            max_chunk = 4500
            if len(text) <= max_chunk:
                translated = translator.translate(text)
                print("[ENGLISH_FILTER] \u2713 Текст полностью переведён на русский")
                return translated
            else:
                sentences = text.split('. ')
                translated_parts = []
                current_chunk = ""
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) < max_chunk:
                        current_chunk += sentence + ". "
                    else:
                        if current_chunk:
                            translated_parts.append(translator.translate(current_chunk))
                        current_chunk = sentence + ". "
                if current_chunk:
                    translated_parts.append(translator.translate(current_chunk))
                translated = " ".join(translated_parts)
                print("[ENGLISH_FILTER] \u2713 Большой текст полностью переведён на русский")
                return translated
        except Exception as e:
            print(f"[ENGLISH_FILTER] \u2717 Ошибка перевода: {e}")

    # ── 3. Пословная фильтрация запрещённых латинских слов ──────────────
    if FORBIDDEN_WORDS_DICT and len(FORBIDDEN_WORDS_DICT) > 0:
        replacements = FORBIDDEN_WORDS_DICT
        print(f"[ENGLISH_FILTER] Используется расширенный словарь ({len(replacements)} слов)")
    else:
        replacements = {
            'however': 'однако', 'moreover': 'более того', 'therefore': 'поэтому',
            'essentially': 'по сути', 'basically': 'в основном',
        }
        print(f"[ENGLISH_FILTER] Используется базовый словарь ({len(replacements)} слов)")

    ALLOWED_LATIN = {
        'ai', 'ok', 'api', 'url', 'http', 'https', 'html', 'css', 'js',
        'python', 'java', 'sql', 'gpu', 'cpu', 'ram', 'rom', 'usb', 'hdmi',
        'pdf', 'jpg', 'png', 'gif', 'mp3', 'mp4', 'wifi', 'lan', 'vpn',
        'google', 'apple', 'microsoft', 'samsung', 'huawei', 'xiaomi', 'sony',
        'intel', 'amd', 'nvidia', 'linux', 'windows', 'macos', 'android', 'ios',
        'youtube', 'telegram', 'instagram', 'facebook', 'twitter', 'whatsapp',
        'ollama', 'llama', 'gpt', 'claude', 'openai',
    }

    words = text.split()
    cleaned_words = []
    replaced_count = 0

    for word in words:
        clean_word = ''.join(c for c in word if c.isalnum()).lower()

        if not clean_word:
            cleaned_words.append(word)
            continue

        has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in clean_word)
        has_latin    = any('a' <= c <= 'z' for c in clean_word)

        if not has_latin:
            cleaned_words.append(word)
            continue

        if has_cyrillic and has_latin:
            cleaned_words.append(word)
            continue

        if clean_word in ALLOWED_LATIN:
            cleaned_words.append(word)
            continue

        if clean_word in replacements:
            suffix = ''.join(c for c in word if not c.isalnum())
            cleaned_words.append(replacements[clean_word] + suffix)
            replaced_count += 1
            print(f"[ENGLISH_FILTER] Заменено: '{word}' → '{replacements[clean_word]}'")
        else:
            replaced_count += 1
            print(f"[ENGLISH_FILTER] Удалено латинское слово: '{word}'")

    if replaced_count > 0:
        print(f"[ENGLISH_FILTER] \u2713 Заменено/удалено: {replaced_count}")

    result = ' '.join(cleaned_words)
    result = re.sub(r'  +', ' ', result).strip()
    return result


def check_spelling_and_suggest(text: str, language: str = "russian") -> dict:
    """
    Проверяет орфографию в тексте и предлагает исправления.
    Возвращает словарь с информацией об ошибках и предложениями.
    
    Returns:
    {
        "has_errors": bool,
        "original": str,
        "suggested": str,
        "corrections": list of tuples (wrong_word, suggested_word)
    }
    """
    try:
        from spellchecker import SpellChecker
        
        if language == "russian":
            spell = SpellChecker(language='ru')
        else:
            spell = SpellChecker(language='en')
        
        words = text.split()
        corrections = []
        corrected_words = []
        
        for word in words:
            # Очищаем слово от знаков препинания для проверки
            clean_word = ''.join(char for char in word if char.isalnum())
            
            if not clean_word:
                corrected_words.append(word)
                continue
            
            # Проверяем орфографию
            if clean_word.lower() in spell:
                corrected_words.append(word)
            else:
                # Слово с ошибкой - ищем исправление
                correction = spell.correction(clean_word.lower())
                if correction and correction != clean_word.lower():
                    # Сохраняем регистр оригинала
                    if clean_word[0].isupper():
                        correction = correction.capitalize()
                    
                    # Восстанавливаем знаки препинания
                    corrected_word = word.replace(clean_word, correction)
                    corrected_words.append(corrected_word)
                    corrections.append((clean_word, correction))
                    print(f"[SPELL_CHECK] Найдена ошибка: '{clean_word}' -> '{correction}'")
                else:
                    corrected_words.append(word)
        
        suggested_text = ' '.join(corrected_words)
        
        return {
            "has_errors": len(corrections) > 0,
            "original": text,
            "suggested": suggested_text,
            "corrections": corrections
        }
        
    except ImportError:
        print("[SPELL_CHECK] pyspellchecker не установлен. Установите: pip install pyspellchecker")
        return {
            "has_errors": False,
            "original": text,
            "suggested": text,
            "corrections": []
        }
    except Exception as e:
        print(f"[SPELL_CHECK] Ошибка проверки орфографии: {e}")
        return {
            "has_errors": False,
            "original": text,
            "suggested": text,
            "corrections": []
        }


# -------------------------
# DuckDuckGo Search helper (named google_search for compatibility)
# -------------------------
def translate_to_russian(text: str) -> str:
    """Переводит текст с английского на русский, сохраняя имена и названия"""
    try:
        print(f"[TRANSLATOR] Начинаю перевод текста...")
        print(f"[TRANSLATOR] Длина текста: {len(text)} символов")
        
        # Используем простой API для перевода
        from deep_translator import GoogleTranslator
        
        translator = GoogleTranslator(source='en', target='ru')
        
        # Переводим по частям, если текст большой
        max_chunk = 4500
        if len(text) <= max_chunk:
            translated = translator.translate(text)
        else:
            # Разбиваем на части по предложениям
            sentences = text.split('. ')
            translated_parts = []
            current_chunk = ""
            
            for sentence in sentences:
                if len(current_chunk) + len(sentence) < max_chunk:
                    current_chunk += sentence + ". "
                else:
                    if current_chunk:
                        translated_parts.append(translator.translate(current_chunk))
                    current_chunk = sentence + ". "
            
            if current_chunk:
                translated_parts.append(translator.translate(current_chunk))
            
            translated = " ".join(translated_parts)
        
        print(f"[TRANSLATOR] Перевод завершён успешно")
        return translated
        
    except ImportError:
        print("[TRANSLATOR] deep-translator не установлен. Установите: pip install deep-translator")
        return text
    except Exception as e:
        print(f"[TRANSLATOR] Ошибка перевода: {e}")
        return text

def analyze_query_type(query: str, language: str) -> dict:
    """
    Анализирует тип запроса и определяет категорию + релевантные источники
    
    Возвращает:
    {
        'category': str,  # Категория запроса
        'domains': list,  # Релевантные домены (пустой = все)
        'keywords': list  # Ключевые слова для улучшения поиска
    }
    """
    query_lower = query.lower()

    # 🕐 ДАТА И ВРЕМЯ (приоритет выше погоды)
    datetime_keywords_ru = ['какое число', 'какой день', 'какое сегодня', 'сегодня число',
                            'текущая дата', 'текущее время', 'который час', 'сколько время',
                            'какой год', 'какой месяц', 'какое время', 'дата сегодня', 'день недели']
    datetime_keywords_en = ['what date', 'what day', 'what time', 'current date', 'current time',
                            'today date', "today's date", 'what year', 'what month', 'day of week']
    if language == "russian":
        if any(kw in query_lower for kw in datetime_keywords_ru):
            return {'category': '🕐 Дата и время',
                    'domains': ['time.is', 'timeanddate.com', 'yandex.ru'],
                    'keywords': ['текущая дата', 'сегодня']}
    else:
        if any(kw in query_lower for kw in datetime_keywords_en):
            return {'category': '🕐 Date & Time',
                    'domains': ['time.is', 'timeanddate.com'],
                    'keywords': ['current date', 'today']}

    # 🌦 ПОГОДА
    weather_keywords_ru = ['погода', 'температура', 'градус', 'прогноз', 'осадки', 'дожд', 'снег', 'ветер', 'климат', 'мороз', 'жара', 'солнечно', 'облачно', 'утром', 'днем', 'днём', 'вечером', 'ночью']
    weather_keywords_en = ['weather', 'temperature', 'forecast', 'rain', 'snow', 'wind', 'climate', 'sunny', 'cloudy']
    
    if language == "russian":
        if any(kw in query_lower for kw in weather_keywords_ru):
            return {
                'category': '🌦 Погода',
                'domains': ['weather', 'meteo', 'gismeteo', 'погода', 'yandex.ru/pogoda'],
                'keywords': ['прогноз погоды', 'температура', 'метеосервис']
            }
    else:
        if any(kw in query_lower for kw in weather_keywords_en):
            return {
                'category': '🌦 Weather',
                'domains': ['weather.com', 'accuweather', 'weatherapi', 'meteo'],
                'keywords': ['weather forecast', 'temperature']
            }
    
    # 📱 ТЕХНИКА / ГАДЖЕТЫ
    tech_keywords_ru = ['телефон', 'смартфон', 'компьютер', 'ноутбук', 'планшет', 'айфон', 'iphone', 'samsung', 'характеристик', 'сравни', 'лучше', 'процессор', 'память', 'экран', 'камера', 'батарея', 'гаджет']
    tech_keywords_en = ['phone', 'smartphone', 'computer', 'laptop', 'tablet', 'iphone', 'samsung', 'specs', 'compare', 'better', 'processor', 'memory', 'screen', 'camera', 'battery', 'gadget']
    
    if language == "russian":
        if any(kw in query_lower for kw in tech_keywords_ru):
            return {
                'category': '📱 Техника',
                'domains': ['ixbt', 'overclockers', 'dns-shop', 'citilink', 'mobile-review', 'tech', 'gadget'],
                'keywords': ['обзор', 'характеристики', 'тест', 'сравнение']
            }
    else:
        if any(kw in query_lower for kw in tech_keywords_en):
            return {
                'category': '📱 Tech',
                'domains': ['gsmarena', 'techradar', 'cnet', 'anandtech', 'tomshardware', 'tech', 'review'],
                'keywords': ['review', 'specs', 'comparison', 'test']
            }
    
    # 🍳 КУЛИНАРИЯ
    cooking_keywords_ru = ['рецепт', 'приготов', 'готов', 'блюдо', 'ингредиент', 'выпека', 'варить', 'жарить', 'запека', 'кухня', 'салат', 'суп', 'десерт', 'торт']
    cooking_keywords_en = ['recipe', 'cook', 'dish', 'ingredient', 'bake', 'fry', 'roast', 'kitchen', 'salad', 'soup', 'dessert', 'cake']
    
    if language == "russian":
        if any(kw in query_lower for kw in cooking_keywords_ru):
            return {
                'category': '🍳 Кулинария',
                'domains': ['russianfood', 'edimdoma', 'povar', 'gastronom', 'recipe', 'рецепт'],
                'keywords': ['рецепт с фото', 'как приготовить', 'пошаговый рецепт']
            }
    else:
        if any(kw in query_lower for kw in cooking_keywords_en):
            return {
                'category': '🍳 Cooking',
                'domains': ['allrecipes', 'foodnetwork', 'epicurious', 'recipe', 'cooking'],
                'keywords': ['recipe with photos', 'how to cook', 'step by step']
            }
    
    # 🧠 ОБУЧЕНИЕ / ОБЪЯСНЕНИЕ
    learning_keywords_ru = ['что такое', 'как работает', 'объясни', 'расскажи', 'чем отличается', 'зачем', 'почему', 'определение', 'значение']
    learning_keywords_en = ['what is', 'how does', 'explain', 'tell me', 'difference', 'why', 'definition', 'meaning']
    
    if language == "russian":
        if any(kw in query_lower for kw in learning_keywords_ru):
            return {
                'category': '🧠 Обучение',
                'domains': ['wikipedia', 'wiki', 'habr', 'образование', 'учебный'],
                'keywords': ['определение', 'объяснение', 'что это']
            }
    else:
        if any(kw in query_lower for kw in learning_keywords_en):
            return {
                'category': '🧠 Learning',
                'domains': ['wikipedia', 'wiki', 'education', 'tutorial'],
                'keywords': ['definition', 'explanation', 'what is']
            }
    
    # ⚙ ПРОГРАММИРОВАНИЕ
    programming_keywords = ['код', 'программ', 'python', 'javascript', 'java', 'c++', 'html', 'css', 'api', 'функция', 'метод', 'класс', 'error', 'bug', 'github', 'stackoverflow', 'code', 'script']
    
    if any(kw in query_lower for kw in programming_keywords):
        return {
            'category': '⚙ Программирование',
            'domains': ['stackoverflow', 'github', 'habr', 'docs', 'documentation', 'developer'],
            'keywords': ['documentation', 'example', 'tutorial', 'code']
        }
    
    # 📰 НОВОСТИ / СОБЫТИЯ
    news_keywords_ru = ['новост', 'событ', 'сегодня', 'вчера', 'произошло', 'случилось']
    news_keywords_en = ['news', 'event', 'today', 'yesterday', 'happened', 'occurred']
    
    if language == "russian":
        if any(kw in query_lower for kw in news_keywords_ru):
            return {
                'category': '📰 Новости',
                'domains': ['news', 'новости', 'lenta', 'tass', 'ria', 'rbc'],
                'keywords': ['новости', 'событие', 'последние новости']
            }
    else:
        if any(kw in query_lower for kw in news_keywords_en):
            return {
                'category': '📰 News',
                'domains': ['news', 'bbc', 'cnn', 'reuters', 'nytimes'],
                'keywords': ['latest news', 'breaking news', 'event']
            }
    
    # ❓ ОБЩИЙ ВОПРОС (по умолчанию)
    return {
        'category': '❓ Общий вопрос',
        'domains': [],  # Поиск везде
        'keywords': []
    }


# ═══════════════════════════════════════════════════════════════════
# УМНАЯ СИСТЕМА ОЦЕНКИ И ФИЛЬТРАЦИИ РЕЗУЛЬТАТОВ ПОИСКА
# ═══════════════════════════════════════════════════════════════════

# Домены с высоким доверием
# ═══════════════════════════════════════════════════════════════════
# WHITELIST / BLACKLIST доменов для оценки качества источников
# ═══════════════════════════════════════════════════════════════════

# Устаревший список — сохранён для обратной совместимости с score_result()
TRUSTED_DOMAINS = [
    'wikipedia.org', 'github.com', 'stackoverflow.com', 'habr.com',
    'python.org', 'developer.mozilla.org', 'docs.microsoft.com',
    'tass.ru', 'ria.ru', 'rbc.ru', 'lenta.ru', 'bbc.com', 'reuters.com',
    'ixbt.com', 'gsmarena.com', 'techradar.com', 'cnet.com',
    'weather.com', 'gismeteo.ru', 'timeanddate.com'
]

# ── Whitelist: доверенные домены с рейтингом (чем выше — тем лучше) ──
# Tier 1 (+40): официальная документация, репозитории, первоисточники
# Tier 2 (+25): крупные авторитетные IT-СМИ и форумы
# Tier 3 (+15): известные технические ресурсы и энциклопедии
SOURCE_WHITELIST: dict = {
    # ── Официальная документация и репозитории ──────────────────────
    "github.com":               40,
    "gitlab.com":               35,
    "docs.python.org":          40,
    "python.org":               40,
    "pypi.org":                 35,
    "docs.microsoft.com":       40,
    "learn.microsoft.com":      40,
    "developer.mozilla.org":    40,
    "developer.apple.com":      40,
    "developer.android.com":    40,
    "developer.chrome.com":     40,
    "docs.oracle.com":          40,
    "docs.docker.com":          40,
    "kubernetes.io":            40,
    "golang.org":               40,
    "rust-lang.org":            40,
    "nodejs.org":               40,
    "reactjs.org":              38,
    "vuejs.org":                38,
    "angular.io":               38,
    "djangoproject.com":        38,
    "flask.palletsprojects.com":38,
    "pytorch.org":              38,
    "tensorflow.org":           38,
    "arxiv.org":                38,
    "openai.com":               35,
    "anthropic.com":            35,
    "huggingface.co":           35,
    "linux.die.net":            35,
    "kernel.org":               38,
    "gnu.org":                  35,
    "postgresql.org":           38,
    "mysql.com":                38,
    "redis.io":                 38,
    "mongodb.com":              35,
    # ── Авторитетные IT-СМИ и форумы ────────────────────────────────
    "stackoverflow.com":        38,
    "superuser.com":            30,
    "serverfault.com":          30,
    "askubuntu.com":            30,
    "unix.stackexchange.com":   30,
    "security.stackexchange.com":30,
    "habr.com":                 30,
    "techradar.com":            25,
    "arstechnica.com":          28,
    "wired.com":                25,
    "theverge.com":             25,
    "engadget.com":             22,
    "zdnet.com":                25,
    "tomshardware.com":         25,
    "anandtech.com":            28,
    "ixbt.com":                 25,
    "3dnews.ru":                22,
    "4pda.ru":                  18,
    "cnews.ru":                 20,
    "vc.ru":                    18,
    "tproger.ru":               20,
    "overclockers.ru":          18,
    # ── Энциклопедии и справочники ───────────────────────────────────
    "wikipedia.org":            25,
    "wikimedia.org":            20,
    "britannica.com":           25,
    "cnet.com":                 22,
    "pcmag.com":                22,
    "gsmarena.com":             25,
    "phonearena.com":           20,
    # ── Надёжные новостные агентства ─────────────────────────────────
    "bbc.com":                  25,
    "bbc.co.uk":                25,
    "reuters.com":              28,
    "bloomberg.com":            28,
    "tass.ru":                  22,
    "ria.ru":                   20,
    "rbc.ru":                   22,
    "kommersant.ru":            22,
    "interfax.ru":              22,
}

# ── Blacklist: агрегаторы, SEO-помойки, ненадёжные сайты ────────────
# Значение — штраф, вычитаемый из итогового скора
SOURCE_BLACKLIST: dict = {
    # Контент-фермы и агрегаторы
    "buzzfeed.com":         -60,
    "listverse.com":        -50,
    "brightside.me":        -50,
    "boredpanda.com":       -50,
    "lifehack.org":         -40,
    "viral":                -40,
    # SEO-дорвеи и маркетинговые сайты
    "seoaudit":             -50,
    "seopult":              -50,
    "rankmath.com":         -40,
    "top10":                -30,
    "topten":               -30,
    "bestof":               -25,
    "compare99":            -40,
    "capterra.com":         -15,
    "g2.com":               -15,
    "getapp.com":           -20,
    "softwaresuggest.com":  -30,
    # Жёлтая пресса и ненадёжные источники
    "dailymail.co.uk":      -40,
    "thesun.co.uk":         -40,
    "infowars.com":         -80,
    "naturalnews.com":      -80,
    # Отзывники и агрегаторы мнений
    "trustpilot.com":       -20,
    "sitejabber.com":       -25,
}

# Слова-маркеры запросов на актуальность
FRESHNESS_KEYWORDS_RU = [
    'последний', 'последняя', 'последнее', 'последние',
    'сейчас', 'текущий', 'текущая', 'актуальный', 'актуально',
    'свежий', 'новый', 'новая', 'новое', 'сегодня', 'недавно',
    'только что', '2024', '2025', '2026'
]
FRESHNESS_KEYWORDS_EN = [
    'latest', 'current', 'now', 'today', 'recent', 'new',
    'updated', 'fresh', 'modern', '2024', '2025', '2026'
]


def needs_freshness_check(query: str) -> bool:
    """Определяет, нужна ли проверка актуальности для запроса."""
    q = query.lower()
    return any(kw in q for kw in FRESHNESS_KEYWORDS_RU + FRESHNESS_KEYWORDS_EN)


def extract_year_from_text(text: str) -> int:
    """Извлекает наиболее свежий год из текста. Возвращает 0 если не найдено."""
    import re
    years = re.findall(r'\b(20[12][0-9])\b', text)
    if years:
        return max(int(y) for y in years)
    return 0


def score_result(result: dict, query: str, freshness_needed: bool = False) -> float:
    """
    Оценивает релевантность результата поиска по нескольким критериям.
    Возвращает float — чем выше, тем лучше.
    
    Критерии:
    - Совпадение ключевых слов запроса в заголовке/описании
    - Домен сайта (трастовые домены получают бонус)
    - Наличие актуальных дат (если запрос требует свежести)
    - Длина описания (короткие описания — меньше информации)
    """
    import re
    
    title = result.get('title', '').lower()
    body = result.get('body', '').lower()
    link = result.get('href', '').lower()
    full_text = title + ' ' + body
    
    score = 0.0
    
    # ── 1. Совпадение ключевых слов ──
    # Очищаем запрос от стоп-слов
    stop_words = {'и', 'в', 'на', 'с', 'по', 'для', 'что', 'как', 'где',
                  'the', 'a', 'an', 'of', 'in', 'for', 'to', 'is', 'how'}
    keywords = [w for w in re.split(r'[\s,?!.]+', query.lower()) 
                if len(w) > 2 and w not in stop_words]
    
    keyword_hits = sum(1 for kw in keywords if kw in full_text)
    if keywords:
        keyword_ratio = keyword_hits / len(keywords)
        score += keyword_ratio * 40  # Макс 40 баллов за ключевые слова
    
    # Бонус за совпадение ключевых слов в заголовке (более ценно)
    title_hits = sum(1 for kw in keywords if kw in title)
    score += title_hits * 5  # +5 за каждое слово в заголовке
    
    # ── 2. Трастовость домена ──
    domain_bonus = sum(10 for trusted in TRUSTED_DOMAINS if trusted in link)
    score += min(domain_bonus, 15)  # Макс 15 баллов за домен
    
    # ── 3. Длина описания (больше текста = больше информации) ──
    body_length = len(result.get('body', ''))
    if body_length > 200:
        score += 10
    elif body_length > 100:
        score += 5
    elif body_length < 30:
        score -= 10  # Штраф за слишком короткое описание
    
    # ── 4. Проверка актуальности ──
    if freshness_needed:
        import datetime
        current_year = datetime.datetime.now().year
        year_in_text = extract_year_from_text(full_text + link)
        
        if year_in_text == current_year:
            score += 20  # Текущий год — отличный бонус
        elif year_in_text == current_year - 1:
            score += 10  # Прошлый год — небольшой бонус
        elif year_in_text > 0 and year_in_text < current_year - 2:
            score -= 20  # Старые страницы — штраф при freshness-запросе
    
    # ── 5. Штраф за нерелевантный контент ──
    # Если ни одного ключевого слова не совпало — штраф
    if keyword_hits == 0 and keywords:
        score -= 15
    
    return score


def filter_and_rank_results(results: list, query: str, min_score: float = -10.0) -> list:
    """
    Фильтрует и сортирует результаты поиска по скору релевантности.
    Отбрасывает явно нерелевантные страницы.
    """
    freshness = needs_freshness_check(query)
    
    scored = []
    for r in results:
        s = score_result(r, query, freshness)
        scored.append((s, r))
        print(f"[SMART_SEARCH] Скор {s:.1f} | {r.get('title', '')[:50]}")
    
    # Сортируем по убыванию скора
    scored.sort(key=lambda x: x[0], reverse=True)
    
    # Отбрасываем слишком нерелевантные
    filtered = [(s, r) for s, r in scored if s >= min_score]
    
    print(f"[SMART_SEARCH] Из {len(results)} результатов осталось {len(filtered)} после фильтрации")
    return [r for _, r in filtered]


def detect_contradiction_or_staleness(page_contents: list, query: str) -> bool:
    """
    Проверяет, противоречат ли страницы друг другу или содержат устаревшие данные.
    Если да — нужен повторный поиск.
    """
    import re, datetime
    
    if not page_contents:
        return False
    
    # Проверка 1: Устаревшие данные при freshness-запросе
    if needs_freshness_check(query):
        current_year = datetime.datetime.now().year
        old_count = 0
        for page in page_contents:
            text = page.get('content', '')
            year = extract_year_from_text(text)
            if year > 0 and year < current_year - 1:
                old_count += 1
        
        # Если больше половины страниц с устаревшими данными
        if old_count > len(page_contents) / 2:
            print(f"[SMART_SEARCH] ⚠️ Обнаружены устаревшие данные в {old_count}/{len(page_contents)} страницах")
            return True
    
    # Проверка 2: Противоречивые версии (например разные версии ПО)
    # Ищем числа вида X.Y.Z (версии) или X.Y (версии/годы)
    version_pattern = re.compile(r'\b(\d+\.\d+(?:\.\d+)?)\b')
    all_versions = []
    for page in page_contents:
        text = page.get('content', '')
        versions = version_pattern.findall(text)
        all_versions.extend(versions)
    
    if all_versions:
        unique_versions = set(all_versions)
        # Если слишком много разных версий — возможно противоречие
        if len(unique_versions) > 5 and needs_freshness_check(query):
            print(f"[SMART_SEARCH] ⚠️ Противоречивые версии: {list(unique_versions)[:5]}")
            return True
    
    return False


# ═══════════════════════════════════════════════════════════════════
# ФИЛЬТР РЕЛЕВАНТНОСТИ СТРАНИЦ (is_relevant_page + score_page_content)
# Применяется ПЕРЕД передачей текста страницы модели.
# ═══════════════════════════════════════════════════════════════════

# Тематические ключевые слова — платформы и ОС
TOPIC_PLATFORM_KEYWORDS = [
    # Мобильные
    'ios', 'android', 'iphone', 'ipad', 'samsung', 'pixel', 'huawei',
    # ПК / ОС
    'windows', 'macos', 'linux', 'ubuntu', 'debian', 'fedora',
    # Браузеры
    'chrome', 'firefox', 'safari', 'edge', 'opera',
    # Облако/сервисы
    'google', 'apple', 'microsoft', 'amazon', 'yandex',
]

# Маркеры конкретных фактов: версии, даты, номера
import re as _re
_FACT_PATTERNS = [
    _re.compile(r'\b\d+\.\d+(?:\.\d+)*\b'),          # версии: 17.4.1, 3.12
    _re.compile(r'\b(19|20)\d{2}\b'),                    # годы: 2023, 2025
    _re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b'), # даты: 12.05.2024
    _re.compile(r'\b(?:january|february|march|april|may|june|july|august|'
                r'september|october|november|december|'
                r'январ|феврал|март|апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)'
                r'\w*\b', _re.IGNORECASE),
    _re.compile(r'\bv?\d+(?:\.\d+){1,3}\b'),           # v1.2.3
    _re.compile(r'\b(?:обновлен|released|вышел|launch|update|релиз)\w*\b', _re.IGNORECASE),
]


def score_page_content(query: str, page_text: str) -> dict:
    """
    Оценивает релевантность текста страницы по трём критериям.
    
    Возвращает словарь:
    {
        "total_score":      float,   # суммарный балл (0-100)
        "keyword_score":    float,   # совпадение ключевых слов (0-40)
        "topic_score":      float,   # упоминание тем/платформ  (0-30)
        "facts_score":      float,   # наличие дат/версий/фактов (0-30)
        "keyword_hits":     int,
        "topic_hits":       list,
        "facts_count":      int,
    }
    """
    stop_words = {
        "и", "в", "на", "с", "по", "для", "что", "как", "где", "это",
        "the", "a", "an", "of", "in", "for", "to", "is", "are", "was",
    }

    # --- Ключевые слова запроса ---
    raw_keywords = _re.split(r"[\s,?!.;:]+", query.lower())
    keywords = [w for w in raw_keywords if len(w) > 2 and w not in stop_words]

    page_lower = page_text.lower()

    keyword_hits = sum(1 for kw in keywords if kw in page_lower)
    if keywords:
        keyword_ratio = keyword_hits / len(keywords)
    else:
        keyword_ratio = 1.0
    keyword_score = round(keyword_ratio * 40, 2)   # макс 40

    # --- Тематика / платформы ---
    # Проверяем запрос И страницу: если тема есть в запросе, ищем её на странице
    query_has_platform = [p for p in TOPIC_PLATFORM_KEYWORDS if p in query.lower()]
    topic_hits = []
    if query_has_platform:
        # Запрос специфичен — ищем только эти платформы
        topic_hits = [p for p in query_has_platform if p in page_lower]
        topic_score = min(len(topic_hits) / max(len(query_has_platform), 1), 1.0) * 30
    else:
        # Запрос общий — любая платформа/тема добавляет балл
        topic_hits = [p for p in TOPIC_PLATFORM_KEYWORDS if p in page_lower]
        topic_score = min(len(topic_hits) * 5, 30)   # +5 за каждую, макс 30
    topic_score = round(topic_score, 2)

    # --- Конкретные факты (версии, даты, названия) ---
    facts_count = 0
    for pattern in _FACT_PATTERNS:
        matches = pattern.findall(page_lower)
        facts_count += len(matches)
    # Нелинейный скор: первые 3 факта дают больше всего очков
    if facts_count == 0:
        facts_score = 0.0
    elif facts_count <= 3:
        facts_score = facts_count * 7.0        # 7/14/21
    elif facts_count <= 10:
        facts_score = 21 + (facts_count - 3) * 1.0  # до 28
    else:
        facts_score = 30.0                     # насыщение
    facts_score = round(min(facts_score, 30), 2)

    total_score = keyword_score + topic_score + facts_score

    return {
        "total_score":   round(total_score, 2),
        "keyword_score": keyword_score,
        "topic_score":   topic_score,
        "facts_score":   facts_score,
        "keyword_hits":  keyword_hits,
        "topic_hits":    topic_hits,
        "facts_count":   facts_count,
    }


def is_relevant_page(query: str, page_text: str, url: str = "",
                     min_total: float = 20.0,
                     min_keyword_ratio: float = 0.20) -> tuple:
    """
    Строгий фильтр релевантности страницы перед передачей текста модели.

    Проверяет 5 условий (все обязательны):
    1. Длина текста        — минимум 200 символов.
    2. URL-фильтр          — отклоняет соцсети, магазины, рекламу, трекеры.
    3. Ключевые слова      — ≥ min_keyword_ratio ключевых слов запроса в тексте.
    4. Тематика            — если запрос содержит платформу (iOS / Android /
                             Windows…), она должна присутствовать на странице.
    5. Суммарный балл      — score_page_content() ≥ min_total.

    Аргументы:
        query:             запрос пользователя
        page_text:         текстовое содержимое страницы
        url:               URL страницы (для URL-фильтра; можно передать "")
        min_total:         порог суммарного балла (по умолч. 20)
        min_keyword_ratio: доля ключевых слов, которая должна совпасть (0.20)

    Возвращает (bool, dict_with_scores, str_reason).
    """
    # ── Проверка 1: минимальная длина текста ────────────────────────
    if not page_text or len(page_text) < 200:
        return False, {}, f"Текст слишком короткий ({len(page_text or '')} символов, нужно ≥200)"

    # ── Проверка 2: URL-фильтр (соцсети, магазины, реклама) ─────────
    # Домены, которые гарантированно не содержат релевантного контента
    _URL_BLOCKLIST = (
        # Социальные сети
        "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com",
        "tiktok.com", "vk.com", "ok.ru", "pinterest.com", "tumblr.com",
        "linkedin.com", "snapchat.com", "telegram.org", "t.me",
        # Видеохостинги (текста нет)
        "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "rutube.ru",
        # Интернет-магазины
        "amazon.com", "amazon.co.uk", "ebay.com", "aliexpress.com",
        "ozon.ru", "wildberries.ru", "avito.ru", "market.yandex.ru",
        "etsy.com", "walmart.com", "bestbuy.com", "newegg.com",
        # Маркетплейсы приложений
        "play.google.com", "apps.apple.com", "microsoft.com/store",
        # Рекламные и трекинговые сети
        "doubleclick.net", "googlesyndication.com", "googletagmanager.com",
        "analytics.google.com", "yandex.ru/adv", "ads.google.com",
        # Агрегаторы цен и отзывов без контента
        "pricespy.com", "price.ru", "hotline.ua", "rozetka.ua",
        # Паблики / форумы без факто-ориентированного контента
        "reddit.com", "quora.com",          # мнения ≠ факты (можно снять)
        "yahoo.com/answers",
    )
    url_lower = (url or "").lower()
    if url_lower:
        for blocked in _URL_BLOCKLIST:
            if blocked in url_lower:
                return (False, {},
                        f"Заблокированный домен: {blocked}")

    # ── Считаем скоры через score_page_content() ────────────────────
    scores = score_page_content(query, page_text)

    stop_words = {
        "и", "в", "на", "с", "по", "для", "что", "как", "где", "это",
        "the", "a", "an", "of", "in", "for", "to", "is", "are", "was",
    }
    raw_keywords = _re.split(r"[\s,?!.;:]+", query.lower())
    keywords = [w for w in raw_keywords if len(w) > 2 and w not in stop_words]

    # ── Проверка 3: ключевые слова ───────────────────────────────────
    if keywords:
        actual_ratio = scores["keyword_hits"] / len(keywords)
        if actual_ratio < min_keyword_ratio:
            return (False, scores,
                    f"Мало ключевых слов запроса: "
                    f"{scores['keyword_hits']}/{len(keywords)} "
                    f"({actual_ratio:.0%} < {min_keyword_ratio:.0%})")

    # ── Проверка 4: тематика (платформа в запросе → нужна на странице) ─
    query_platforms = [p for p in TOPIC_PLATFORM_KEYWORDS if p in query.lower()]
    if query_platforms and not scores["topic_hits"]:
        return (False, scores,
                f"Запрос о платформах {query_platforms}, "
                f"но они отсутствуют на странице")

    # ── Проверка 5: суммарный балл ───────────────────────────────────
    if scores["total_score"] < min_total:
        return (False, scores,
                f"Низкий суммарный балл: "
                f"{scores['total_score']:.1f} < {min_total}")

    return True, scores, "OK"


def refine_search_query(original_query: str, attempt: int = 1) -> str:
    """
    Генерирует уточнённый поисковый запрос для повторного поиска.
    attempt=1 → добавляем год; attempt=2 → более конкретная формулировка.
    """
    import datetime
    year = datetime.datetime.now().year

    if attempt == 1:
        # Добавляем текущий год для более актуальных результатов
        return f"{original_query} {year}"
    else:
        # Упрощаем запрос до ключевых слов + добавляем "официальный" / "обзор"
        stop_words = {
            "и", "в", "на", "с", "по", "для", "что", "как", "где",
            "the", "a", "an", "of", "in", "for", "to",
        }
        raw = _re.split(r"[\s,?!.;:]+", original_query.lower())
        keywords = [w for w in raw if len(w) > 3 and w not in stop_words]
        core = " ".join(keywords[:5])
        suffix = "официально обзор" if any(c in original_query for c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя") else "official review"
        return f"{core} {suffix} {year}"


def google_search(query: str, num_results: int = 5, region: str = "wt-wt", language: str = "russian"):
    """Поиск через DuckDuckGo API (ddgs) с умной фильтрацией по типу запроса"""
    print(f"[DUCKDUCKGO_SEARCH] Запуск поиска...")
    print(f"[DUCKDUCKGO_SEARCH] Запрос: {query}")
    print(f"[DUCKDUCKGO_SEARCH] Регион: {region}")
    print(f"[DUCKDUCKGO_SEARCH] Количество результатов: {num_results}")
    
    # 🔍 АНАЛИЗ ТИПА ЗАПРОСА
    query_analysis = analyze_query_type(query, language)
    print(f"[DUCKDUCKGO_SEARCH] 📊 Категория запроса: {query_analysis['category']}")
    print(f"[DUCKDUCKGO_SEARCH] 🎯 Релевантные домены: {query_analysis['domains']}")
    
    # Улучшаем запрос ключевыми словами если они есть
    enhanced_query = query
    if query_analysis['keywords']:
        enhanced_query = f"{query} {' '.join(query_analysis['keywords'][:2])}"
        print(f"[DUCKDUCKGO_SEARCH] ✨ Улучшенный запрос: {enhanced_query}")

    try:
        # ddgs is optional dependency: pip install ddgs
        from ddgs import DDGS

        print(f"[DUCKDUCKGO_SEARCH] Отправка запроса...")
        with DDGS() as ddgs:
            # Получаем больше результатов для фильтрации
            raw_results = list(ddgs.text(enhanced_query, region=region, max_results=num_results * 3))

        print(f"[DUCKDUCKGO_SEARCH] Получено сырых результатов: {len(raw_results)}")
        
        # 🎯 ШАГ 1: ДОМЕННАЯ ФИЛЬТРАЦИЯ (по категории запроса)
        domain_filtered = []
        if query_analysis['domains']:
            for result in raw_results:
                link = result.get('href', '').lower()
                if any(domain in link for domain in query_analysis['domains']):
                    domain_filtered.append(result)
            
            # Если мало доменных результатов — добавляем из всех
            if len(domain_filtered) < max(2, num_results // 2):
                domain_filtered = raw_results
        else:
            domain_filtered = raw_results
        
        # 🎯 ШАГ 2: УМНЫЙ СКОРИНГ И РАНЖИРОВАНИЕ
        print(f"[DUCKDUCKGO_SEARCH] 📊 Запускаю скоринг {len(domain_filtered)} результатов...")
        ranked_results = filter_and_rank_results(domain_filtered, query)
        
        # Берём топ N результатов
        results = ranked_results[:num_results]
        
        # Если после фильтрации совсем мало — берём из всех сырых
        if len(results) < 2:
            print(f"[DUCKDUCKGO_SEARCH] ⚠️ Мало результатов после скоринга, берём всё...")
            results = raw_results[:num_results]
        
        print(f"[DUCKDUCKGO_SEARCH] ✅ Итого результатов после ранжирования: {len(results)}")

        if not results:
            print(f"[DUCKDUCKGO_SEARCH] Нет результатов поиска")
            return "Ничего не найдено по вашему запросу."

        search_results = []
        for i, result in enumerate(results, 1):
            title = result.get('title', 'Без заголовка')
            body = result.get('body', 'Нет описания')
            link = result.get('href', '')
            search_results.append(f"[Результат {i}]\nЗаголовок: {title}\nОписание: {body}\nСсылка: {link}")
            print(f"[DUCKDUCKGO_SEARCH] Результат {i}: {title[:50]}...")

        final_results = "\n\n".join(search_results)
        print(f"[DUCKDUCKGO_SEARCH] Поиск завершён успешно. Длина результатов: {len(final_results)} символов")
        print(f"[DUCKDUCKGO_SEARCH] 📊 Итоговая статистика: категория={query_analysis['category']}, результатов={len(results)}")
        return final_results

    except ImportError:
        # FALLBACK: Используем простой веб-скрейпинг DuckDuckGo HTML
        print(f"[DUCKDUCKGO_SEARCH] ⚠️ Библиотека ddgs не установлена, используем fallback...")
        try:
            return fallback_web_search(enhanced_query, num_results, language)
        except Exception as fallback_error:
            error_msg = f"⚠️ Установите библиотеку ddgs: pip install ddgs\nОшибка fallback: {fallback_error}"
            print(f"[DUCKDUCKGO_SEARCH] {error_msg}")
            return error_msg
    except Exception as e:
        error_msg = f"⚠️ Ошибка поиска: {e}"
        print(f"[DUCKDUCKGO_SEARCH] {error_msg}")
        return error_msg

def fetch_page_content(url: str, max_chars: int = 5000) -> str:
    """
    Загружает и извлекает текстовое содержимое веб-страницы
    
    Args:
        url: URL страницы для загрузки
        max_chars: Максимальное количество символов для возврата
    
    Returns:
        Текстовое содержимое страницы или сообщение об ошибке
    """
    try:
        print(f"[FETCH_PAGE] Загрузка страницы: {url[:50]}...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Используем BeautifulSoup для извлечения текста
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Удаляем скрипты и стили
            for script in soup(['script', 'style', 'nav', 'header', 'footer']):
                script.decompose()
            
            # Извлекаем текст
            text = soup.get_text(separator=' ', strip=True)
            
            # Очищаем от множественных пробелов
            import re
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Ограничиваем размер
            if len(text) > max_chars:
                text = text[:max_chars] + "..."
            
            print(f"[FETCH_PAGE] ✓ Загружено {len(text)} символов")
            return text
            
        except ImportError:
            # Если BeautifulSoup не установлен, используем простую регулярку
            import re
            # Удаляем HTML теги
            text = re.sub(r'<[^>]+>', '', response.text)
            # Очищаем от множественных пробелов
            text = re.sub(r'\s+', ' ', text).strip()
            # Ограничиваем размер
            if len(text) > max_chars:
                text = text[:max_chars] + "..."
            print(f"[FETCH_PAGE] ✓ Загружено {len(text)} символов (без BS4)")
            return text
            
    except Exception as e:
        print(f"[FETCH_PAGE] ✗ Ошибка загрузки {url}: {e}")
        return f"[Ошибка загрузки страницы: {str(e)[:100]}]"

# ═══════════════════════════════════════════════════════════════════
# ПРОВЕРКА СВЕЖЕСТИ И ФАКТОВ ПЕРЕД ГЕНЕРАЦИЕЙ ОТВЕТА
# ═══════════════════════════════════════════════════════════════════

def extract_year(text: str) -> int:
    """
    Извлекает наиболее свежий год из текста страницы или метаданных.
    Ищет как явные годы (2023), так и даты в заголовках HTTP/HTML.

    Возвращает год (int) или 0 если не найдено.
    """
    import re, datetime

    # 1. Ищем год в формате мета-тега или HTTP-заголовка:
    #    <meta ... content="2024-05-12" ...>  или  Last-Modified: 2024
    meta_match = re.search(
        r'(?:content|datetime|date|published|modified|last.modified)["\s:=]+(\d{4})',
        text, re.IGNORECASE
    )
    if meta_match:
        y = int(meta_match.group(1))
        current = datetime.datetime.now().year
        if 2000 <= y <= current:
            return y

    # 2. Ищем даты в тексте: «15 мая 2024», «May 15, 2024», «2024-05-15»
    date_patterns = [
        r'\b(20[12]\d)[.\-/]\d{1,2}[.\-/]\d{1,2}\b',   # 2024-05-15
        r'\b\d{1,2}[.\-/]\d{1,2}[.\-/](20[12]\d)\b',   # 15.05.2024
        r'\b(?:january|february|march|april|may|june|july|august|'
        r'september|october|november|december|'
        r'январ\w*|феврал\w*|март\w*|апрел\w*|май|июн\w*|июл\w*|'
        r'август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)'
        r'\s+\d{1,2}[,\s]+(20[12]\d)\b',                # May 15, 2024
        r'\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|'
        r'september|october|november|december|'
        r'январ\w*|феврал\w*|март\w*|апрел\w*|май|июн\w*|июл\w*|'
        r'август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)'
        r'\s+(20[12]\d)\b',                              # 15 мая 2024
    ]
    years_found = []
    for pat in date_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            # Группа с годом — последняя захватывающая группа
            for g in reversed(m.groups()):
                if g and re.fullmatch(r'20[12]\d', g):
                    years_found.append(int(g))
                    break

    # 3. Запасной вариант — любое четырёхзначное число 2010-текущий год
    fallback = re.findall(r'\b(20[12]\d)\b', text)
    years_found.extend(int(y) for y in fallback)

    if years_found:
        current_year = datetime.datetime.now().year
        valid = [y for y in years_found if 2000 <= y <= current_year]
        if valid:
            return max(valid)

    return 0


def has_facts(text: str) -> bool:
    """
    Проверяет, содержит ли текст конкретные факты:
    версии ПО, даты, числовые данные, названия функций/релизов.

    Возвращает True если найдено ≥ 2 различных фактических паттернов.
    """
    import re

    fact_patterns = [
        re.compile(r'\b\d+\.\d+(?:\.\d+)*\b'),              # версии: 3.12, 17.4.1
        re.compile(r'\bv?\d+(?:\.\d+){1,3}\b'),             # v1.2.3
        re.compile(r'\b(19|20)\d{2}\b'),                     # годы: 2023
        re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b'),  # даты: 12.05.2024
        re.compile(                                           # месяцы
            r'\b(?:january|february|march|april|may|june|july|august|'
            r'september|october|november|december|'
            r'январ|феврал|март|апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)'
            r'\w*\b', re.IGNORECASE
        ),
        re.compile(                                           # ключевые слова релизов
            r'\b(?:released?|вышел|вышла|обновлен\w*|запущен\w*|launch\w*|'
            r'релиз|update|changelog|новая\s+версия|new\s+version)\b',
            re.IGNORECASE
        ),
        re.compile(r'\b\d+\s*(?:мб|гб|mb|gb|мс|ms|fps|rpm|ghz|ггц|кб|kb)\b',
                   re.IGNORECASE),                           # технические числа
    ]

    hits = 0
    for pattern in fact_patterns:
        if pattern.search(text):
            hits += 1
        if hits >= 2:
            return True

    return False


# ═══════════════════════════════════════════════════════════════════
# ПАЙПЛАЙН КАЧЕСТВА: свежесть, факты, версии, защита от галлюцинаций
# ═══════════════════════════════════════════════════════════════════

# Ключевые слова, означающие «нужна актуальная информация»
_FRESHNESS_TRIGGER_WORDS = [
    # Русские
    "последняя", "последний", "последнее", "последние",
    "сейчас", "актуальная", "актуальный", "актуальное", "актуальные",
    "свежая", "свежий", "свежее", "свежие",
    "текущая", "текущий", "текущее", "текущие",
    "новая версия", "новый релиз", "вышла", "вышел", "вышло",
    # Английские
    "latest", "current", "newest", "recent", "now",
    "latest version", "current version", "new release",
]


def is_fresh_page(text: str, query: str) -> tuple:
    """
    Проверяет, является ли страница достаточно свежей для данного запроса.

    Логика:
    - Если запрос содержит слова актуальности (latest, последняя и т.д.),
      страница должна содержать год >= current_year - 1.
    - Если год не найден вообще → страница считается свежей (неизвестно).
    - Если запрос не требует актуальности → всегда True.

    Возвращает (is_ok: bool, found_year: int, reason: str).
    """
    import datetime

    query_lower = query.lower()
    needs_fresh = any(kw in query_lower for kw in _FRESHNESS_TRIGGER_WORDS)

    if not needs_fresh:
        return True, 0, "freshness_not_required"

    current_year = datetime.datetime.now().year
    found_year = extract_year(text)

    if found_year == 0:
        # Год не найден → не отклоняем (нет доказательства устарелости)
        return True, 0, "year_not_found"

    threshold = current_year - 1
    if found_year >= threshold:
        return True, found_year, f"fresh ({found_year} >= {threshold})"

    return False, found_year, f"stale: {found_year} < {threshold}"


def has_real_facts(text: str) -> tuple:
    """
    Проверяет, содержит ли текст конкретные факты перед передачей модели.

    Проверяет наличие:
    1. Версий ПО (X.Y, X.Y.Z, vX.Y)
    2. Дат (числовых или словесных)
    3. Ключевых слов релизов / функций
    4. Технических чисел с единицами измерения

    Требуется минимум 2 разных типа фактов.

    Возвращает (has_facts: bool, facts_found: list[str], count: int).
    """
    import re

    checks = [
        ("version_dotted",  re.compile(r'\b\d+\.\d+(?:\.\d+)*\b')),
        ("version_v_prefix", re.compile(r'\bv\d+(?:\.\d+){1,3}\b', re.IGNORECASE)),
        ("year_4digit",     re.compile(r'\b(19|20)\d{2}\b')),
        ("date_numeric",    re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b')),
        ("month_word",      re.compile(
            r'\b(?:january|february|march|april|may|june|july|august|'
            r'september|october|november|december|'
            r'январ|феврал|март|апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)'
            r'\w*\b', re.IGNORECASE)),
        ("release_keyword", re.compile(
            r'\b(?:released?|вышел|вышла|обновлен\w*|запущен\w*|launch\w*|'
            r'релиз|changelog|новая\s+версия|new\s+version|feature|функция)\b',
            re.IGNORECASE)),
        ("tech_measurement", re.compile(
            r'\b\d+\s*(?:мб|гб|тб|mb|gb|tb|мс|ms|fps|rpm|ghz|ггц|кб|kb|px|dp)\b',
            re.IGNORECASE)),
    ]

    found_types = []
    for name, pattern in checks:
        if pattern.search(text):
            found_types.append(name)

    ok = len(found_types) >= 2
    return ok, found_types, len(found_types)


def filter_pages(pages: list, query: str, max_age_years: int = 1) -> list:
    """
    Главный фильтр качества страниц перед передачей текста модели.

    Применяет 4 последовательных проверки:
    1) is_relevant_page(query, text, url) — URL-блокировка соцсетей/магазинов/рекламы,
       ключевые слова, тематика платформы, суммарный балл.
       Страницы, не прошедшие этот фильтр, НЕ передаются модели.
    2) is_fresh_page — отклоняет устаревшие страницы при freshness-запросах.
    3) has_real_facts — отклоняет страницы без конкретных фактов (версии, даты…).

    Аргументы:
        pages:         список dict с ключами 'content', 'url'
        query:         исходный запрос пользователя
        max_age_years: порог устарелости (по умолч. 1 год)

    Возвращает отфильтрованный список страниц.
    Страницы, не прошедшие любой из фильтров, гарантированно исключаются.
    """
    accepted = []

    for page in pages:
        text = page.get('content', '')
        url  = page.get('url', '')
        label = url[:70] or '<без url>'

        # ── Проверка 1: релевантность + URL-блокировка ────────────
        rel_ok, rel_scores, rel_reason = is_relevant_page(query, text, url)
        if not rel_ok:
            print(f"[FILTER_PAGES] ❌ Нерелевантна ({rel_reason}): {label}")
            continue

        # ── Проверка 2: свежесть ──────────────────────────────────
        fresh_ok, found_year, fresh_reason = is_fresh_page(text, query)
        if not fresh_ok:
            print(f"[FILTER_PAGES] ❌ Устаревшая ({found_year}): {label}")
            continue

        # ── Проверка 3: наличие фактов ────────────────────────────
        facts_ok, fact_types, fact_count = has_real_facts(text)
        if not facts_ok:
            print(f"[FILTER_PAGES] ❌ Мало фактов ({fact_count}/2): {label}")
            continue

        print(
            f"[FILTER_PAGES] ✅ Принята | "
            f"score={rel_scores.get('total_score', 0):.0f} "
            f"year={found_year or '?'} "
            f"facts={fact_count}: {url[:65]}"
        )
        accepted.append(page)

    print(f"[FILTER_PAGES] Итого: {len(accepted)}/{len(pages)} страниц прошли все фильтры")
    return accepted


def retry_search_if_needed(
    page_contents: list,
    query: str,
    num_results: int = 5,
    region: str = "wt-wt",
    language: str = "russian",
    max_pages: int = 3,
    max_attempts: int = 2,
    min_good_sources: int = 2,
) -> list:
    """
    Если отфильтрованных источников меньше min_good_sources,
    автоматически повторяет поиск с уточнёнными запросами.

    При повторном поиске к запросу добавляются:
    «latest version», «release», текущий год — чтобы получить свежие страницы.

    Возвращает дополненный список страниц.
    """
    import re, datetime

    if len(page_contents) >= min_good_sources:
        return page_contents

    current_year = datetime.datetime.now().year
    existing_urls = {p['url'] for p in page_contents}

    for attempt in range(1, max_attempts + 1):
        if len(page_contents) >= min_good_sources:
            break

        # Уточняем запрос: добавляем свежесть-маркеры
        if attempt == 1:
            retry_query = f"{query} latest version release {current_year}"
        else:
            # Второй вариант: упрощаем запрос до ключевых слов + год
            stop = {'и','в','на','с','по','для','что','как','где',
                    'the','a','an','of','in','for','to'}
            words = [w for w in re.split(r'[\s,?!.;:]+', query.lower())
                     if len(w) > 3 and w not in stop]
            retry_query = f"{' '.join(words[:5])} release changelog {current_year}"

        print(f"[RETRY_SEARCH] 🔎 Попытка {attempt}/{max_attempts}: «{retry_query}»")

        retry_results = google_search(retry_query, num_results, region, language)
        if "Ничего не найдено" in retry_results or "Ошибка" in retry_results:
            print(f"[RETRY_SEARCH] ⚠️ Поиск пустой на попытке {attempt}")
            continue

        urls = re.findall(r'Ссылка: (https?://[^\s]+)', retry_results)

        for url in urls[:max_pages]:
            if url in existing_urls:
                continue
            page_text = fetch_page_content(url, max_chars=3000)
            if not page_text or "[Ошибка" in page_text:
                continue

            candidate = {"url": url, "content": page_text}
            filtered = filter_pages([candidate], query)
            if filtered:
                page_contents.append(filtered[0])
                existing_urls.add(url)
                print(f"[RETRY_SEARCH] ✅ Добавлена: {url[:70]}")

    status = "достаточно" if len(page_contents) >= min_good_sources else "недостаточно"
    print(
        f"[RETRY_SEARCH] Итого источников: {len(page_contents)} "
        f"(нужно {min_good_sources}) — {status}"
    )
    return page_contents


# ─────────────────────────────────────────────────────────────────────
# ЗАЩИТА ОТ ГАЛЛЮЦИНАЦИЙ: извлечение и валидация версий из источников
# ─────────────────────────────────────────────────────────────────────

def extract_versions_from_sources(page_contents: list) -> list:
    """
    Извлекает все версии ПО (формат X.Y или X.Y.Z) из отфильтрованных страниц.

    Возвращает список строк версий, отсортированных от новейшей к старейшей.
    Пример: ['17.4.1', '17.4', '16.0.3']
    """
    import re
    from functools import cmp_to_key

    version_pattern = re.compile(r'\b(\d{1,3}\.\d{1,3}(?:\.\d{1,4})?(?:\.\d{1,4})?)\b')
    all_versions = set()

    for page in page_contents:
        text = page.get('content', '')
        matches = version_pattern.findall(text)
        for v in matches:
            parts = v.split('.')
            # Отсеиваем явные годы (20xx.x) и IP-подобные (192.168...)
            if len(parts) >= 2:
                major = int(parts[0])
                if 2010 <= major <= 2040:
                    continue  # это год, не версия
                if major > 255:
                    continue  # слишком большое число
            all_versions.add(v)

    def version_key(v: str):
        """Сравнивает версии как кортежи чисел."""
        try:
            return tuple(int(x) for x in v.split('.'))
        except ValueError:
            return (0,)

    sorted_versions = sorted(all_versions, key=version_key, reverse=True)
    return sorted_versions


def validate_versions_before_answer(
    page_contents: list,
    query: str,
    max_version_age_years: int = 3,
) -> dict:
    """
    Проверяет версии из источников перед генерацией ответа.
    Защищает от галлюцинаций: модель не получит данные,
    если все версии слишком старые или противоречивы.

    Логика:
    - Извлекает все версии из page_contents.
    - Выбирает самую новую версию.
    - Если версия слишком старая (год публикации < current-max_version_age_years)
      И запрос требует актуальности → рекомендует повторный поиск.
    - Если версий совсем нет → нейтральный статус (не блокируем генерацию).

    Возвращает dict:
    {
        "ok": bool,          # True = можно генерировать ответ
        "retry": bool,       # True = нужен повторный поиск
        "best_version": str, # Лучшая найденная версия или ""
        "all_versions": list,
        "reason": str,
    }
    """
    import datetime

    versions = extract_versions_from_sources(page_contents)

    # Нет версий вообще — не блокируем (возможно, запрос не про версии)
    if not versions:
        return {
            "ok": True, "retry": False,
            "best_version": "", "all_versions": [],
            "reason": "no_versions_found"
        }

    best_version = versions[0]

    # Определяем, требует ли запрос актуальности
    query_lower = query.lower()
    needs_fresh = any(kw in query_lower for kw in _FRESHNESS_TRIGGER_WORDS)

    if not needs_fresh:
        return {
            "ok": True, "retry": False,
            "best_version": best_version, "all_versions": versions,
            "reason": "freshness_not_required"
        }

    # Проверяем свежесть через год публикации страниц
    current_year = datetime.datetime.now().year
    threshold_year = current_year - max_version_age_years

    # Собираем годы публикации всех страниц
    page_years = []
    for page in page_contents:
        y = extract_year(page.get('content', ''))
        if y > 0:
            page_years.append(y)

    if page_years:
        newest_page_year = max(page_years)
        if newest_page_year < threshold_year:
            print(
                f"[VERSION_GUARD] ⚠️ Все страницы устаревшие "
                f"(новейший год={newest_page_year}, порог={threshold_year}). "
                f"Версия «{best_version}» может быть неактуальной."
            )
            return {
                "ok": False, "retry": True,
                "best_version": best_version, "all_versions": versions,
                "reason": (
                    f"stale_sources: newest page year {newest_page_year} "
                    f"< threshold {threshold_year}"
                )
            }

    print(
        f"[VERSION_GUARD] ✅ Версия «{best_version}» из {len(versions)} найденных. "
        f"Все источники актуальны."
    )
    return {
        "ok": True, "retry": False,
        "best_version": best_version, "all_versions": versions,
        "reason": "version_validated"
    }


# ═══════════════════════════════════════════════════════════════════
# СИСТЕМА ОЦЕНКИ КАЧЕСТВА ИСТОЧНИКОВ
# ═══════════════════════════════════════════════════════════════════

def source_quality_score(url: str, text: str, query: str = "") -> dict:
    """
    Оценивает качество источника по 6 критериям и возвращает итоговый балл.

    Критерии (максимум 100 баллов):
    1. Домен — whitelist / blacklist / нейтральный  (−80 … +40)
    2. Техническое содержание — код, команды, API    (0 … +20)
    3. Длина текста по теме                          (0 … +15)
    4. Наличие дат и фактов                          (0 … +15)
    5. Совпадение темы страницы с запросом           (0 … +20)
    6. Признаки авторства и структурности            (0 … +10)

    Аргументы:
        url:   URL источника
        text:  текстовое содержимое страницы
        query: запрос пользователя (для пункта 5)

    Возвращает dict:
    {
        "total":        float,   # итоговый балл
        "domain_score": float,   # балл за домен
        "tech_score":   float,   # техническое содержание
        "length_score": float,   # длина текста
        "facts_score":  float,   # факты и даты
        "topic_score":  float,   # совпадение темы
        "author_score": float,   # авторство / структура
        "tier":         str,     # "whitelist" / "blacklist" / "neutral"
        "domain":       str,     # извлечённый домен
    }
    """
    import re, datetime

    url_lower = url.lower()
    text_lower = text.lower() if text else ""

    # ── 1. Домен: whitelist / blacklist ─────────────────────────────
    domain_score = 0.0
    tier = "neutral"
    matched_domain = ""

    # Извлекаем основной домен из URL
    domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url_lower)
    raw_domain = domain_match.group(1) if domain_match else url_lower[:60]

    # Проверяем whitelist (от наиболее специфичного к общему)
    for wl_domain, wl_bonus in sorted(SOURCE_WHITELIST.items(),
                                       key=lambda x: len(x[0]), reverse=True):
        if wl_domain in raw_domain:
            domain_score = float(wl_bonus)
            tier = "whitelist"
            matched_domain = wl_domain
            break

    # Проверяем blacklist (штраф суммируется, если нет бонуса whitelist)
    if tier != "whitelist":
        for bl_pattern, bl_penalty in SOURCE_BLACKLIST.items():
            if bl_pattern in raw_domain or bl_pattern in url_lower:
                domain_score += float(bl_penalty)
                tier = "blacklist"
                matched_domain = bl_pattern
                break

    # Ограничиваем диапазон
    domain_score = max(-80.0, min(40.0, domain_score))

    # ── 2. Техническое содержание ────────────────────────────────────
    tech_patterns = [
        r'```',                          # блоки кода
        r'def \w+\(',                  # функции Python
        r'function\s+\w+\s*\(',        # JavaScript функции
        r'class \w+',                  # классы
        r'import \w+',                 # импорты
        r'\$ \w+',                       # shell-команды
        r'--\w+',                        # CLI флаги
        r'api',                      # упоминание API
        r'https?://[^\s]{10,}',          # реальные URL в тексте
        r'(?:curl|wget|npm|pip|apt|brew|docker|kubectl)',
        r'\d+\.\d+\.\d+',           # версии X.Y.Z
        r'<\w+[^>]*>',                   # HTML/XML теги (в сыром тексте)
    ]
    tech_hits = sum(1 for p in tech_patterns if re.search(p, text[:5000]))
    tech_score = min(20.0, tech_hits * 2.5)

    # ── 3. Длина текста ──────────────────────────────────────────────
    text_len = len(text)
    if text_len >= 3000:
        length_score = 15.0
    elif text_len >= 1500:
        length_score = 10.0
    elif text_len >= 600:
        length_score = 5.0
    elif text_len < 200:
        length_score = -5.0   # штраф за слишком мало текста
    else:
        length_score = 0.0

    # ── 4. Факты: версии, даты, числа ───────────────────────────────
    fact_patterns_list = [
        re.compile(r'\d+\.\d+(?:\.\d+)*'),              # версии
        re.compile(r'(19|20)\d{2}'),                     # годы
        re.compile(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}'),  # даты
        re.compile(r'(?:january|february|march|april|may|june|july|august|'
                   r'september|october|november|december|январ|феврал|март|'
                   r'апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*',
                   re.IGNORECASE),
        re.compile(r'(?:released?|вышел|вышла|релиз|changelog|'
                   r'обновлен\w*|запущен\w*)', re.IGNORECASE),
        re.compile(r'\d+\s*(?:мб|гб|mb|gb|мс|ms|fps|ghz|ггц|px)',
                   re.IGNORECASE),
    ]
    fact_types_found = sum(1 for fp in fact_patterns_list if fp.search(text_lower))
    facts_score = min(15.0, fact_types_found * 3.0)

    # ── 5. Совпадение темы с запросом ───────────────────────────────
    topic_score = 0.0
    if query:
        stop = {'и','в','на','с','по','для','что','как','где','это',
                'the','a','an','of','in','for','to','is','are','was'}
        kws = [w for w in re.split(r'[\s,?!.;:]+', query.lower())
               if len(w) > 2 and w not in stop]
        if kws:
            hits = sum(1 for kw in kws if kw in text_lower)
            ratio = hits / len(kws)
            topic_score = round(min(20.0, ratio * 20.0), 2)

            # Бонус если ключевые слова встречаются в первых 500 символах
            head = text_lower[:500]
            head_hits = sum(1 for kw in kws if kw in head)
            topic_score = min(20.0, topic_score + head_hits * 1.5)

    # ── 6. Авторство и структура ─────────────────────────────────────
    author_score = 0.0
    author_markers = [
        r'(?:by|автор|author|written by|опубликовано|published)',
        r'(?:updated|обновлено|дата публикации|date)',
        r'(?:editor|редактор|contributor)',
        r'<h[1-3]',         # структурные заголовки в сыром HTML
        r'#{1,3} \w',       # markdown-заголовки
    ]
    author_hits = sum(1 for p in author_markers
                      if re.search(p, text[:3000], re.IGNORECASE))
    author_score = min(10.0, author_hits * 3.0)

    # ── Итог ─────────────────────────────────────────────────────────
    total = domain_score + tech_score + length_score + facts_score + topic_score + author_score

    return {
        "total":        round(total, 2),
        "domain_score": domain_score,
        "tech_score":   round(tech_score, 2),
        "length_score": length_score,
        "facts_score":  round(facts_score, 2),
        "topic_score":  round(topic_score, 2),
        "author_score": round(author_score, 2),
        "tier":         tier,
        "domain":       matched_domain or raw_domain[:40],
    }


def rank_and_select_sources(
    page_contents: list,
    query: str,
    top_n: int = 3,
    min_quality_score: float = 20.0,
    min_sources: int = 2,
) -> tuple:
    """
    Оценивает качество каждого источника, сортирует по баллу и выбирает лучшие.

    Если после фильтрации остаётся меньше min_sources качественных источников,
    возвращает флаг needs_retry=True — сигнал для повторного поиска.

    Аргументы:
        page_contents:      список dict{'url', 'content', ...}
        query:              запрос пользователя
        top_n:              максимальное число источников в ответе (2–3)
        min_quality_score:  минимальный балл для «качественного» источника
        min_sources:        минимум качественных источников перед retry

    Возвращает (ranked_pages: list, needs_retry: bool):
        ranked_pages  — отсортированный список страниц с добавленным ключом
                        'quality_score' (только ≥ min_quality_score)
        needs_retry   — True если нужен повторный поиск
    """
    if not page_contents:
        return [], True

    scored = []
    for page in page_contents:
        url   = page.get("url", "")
        text  = page.get("content", "")
        scores = source_quality_score(url, text, query)
        page_with_score = dict(page)
        page_with_score["quality_score"]  = scores["total"]
        page_with_score["quality_detail"] = scores
        scored.append(page_with_score)

        tier_icon = "✅" if scores["tier"] == "whitelist" else (
                    "❌" if scores["tier"] == "blacklist" else "⚪")
        print(
            f"[SOURCE_QUALITY] {tier_icon} {scores['total']:6.1f}pts "
            f"| domain={scores['domain_score']:+.0f} "
            f"tech={scores['tech_score']:.0f} "
            f"facts={scores['facts_score']:.0f} "
            f"topic={scores['topic_score']:.0f} "
            f"| {url[:65]}"
        )

    # Сортируем от лучшего к худшему
    scored.sort(key=lambda p: p["quality_score"], reverse=True)

    # Отбираем только источники выше порога качества
    quality_pages = [p for p in scored if p["quality_score"] >= min_quality_score]

    needs_retry = len(quality_pages) < min_sources

    if needs_retry:
        print(
            f"[SOURCE_QUALITY] ⚠️ Качественных источников: {len(quality_pages)} "
            f"(нужно ≥{min_sources}, порог ≥{min_quality_score}пт). "
            f"Нужен повторный поиск."
        )
        # Возвращаем всё что есть — retry обработает caller
        best = scored[:top_n]
    else:
        best = quality_pages[:top_n]
        print(
            f"[SOURCE_QUALITY] ✅ Выбрано {len(best)} из {len(scored)} источников "
            f"(топ {top_n}, порог {min_quality_score}пт)"
        )

    return best, needs_retry




# ═══════════════════════════════════════════════════════════════════════════
# МОДУЛЬНЫЙ ПАЙПЛАЙН ОПРЕДЕЛЕНИЯ АКТУАЛЬНОЙ ВЕРСИИ ПО / ПРОШИВКИ / СИСТЕМЫ
# Архитектура: search → filter → extract → validate → answer
#
# Универсален для любого ПО: iOS, Android, Python, Firefox, Windows и т.д.
# Активируется автоматически при запросах вида:
#   «последняя версия X», «что нового в X», «latest version X», «X changelog»
# ═══════════════════════════════════════════════════════════════════════════

# ── Ключевые слова, однозначно указывающие на запрос о версии ───────────
_VERSION_INTENT_KEYWORDS = [
    # Русские
    "последняя версия", "актуальная версия", "текущая версия",
    "новая версия", "что нового", "что нового в", "изменения в",
    "обновление до", "вышла версия", "релиз", "changelog",
    "release notes", "список изменений", "что изменилось",
    # Английские
    "latest version", "current version", "newest version",
    "what's new", "what is new", "release notes", "changelog",
    "new features", "latest release", "current release",
    "latest update", "version history",
]

# ── Шаблоны поисковых запросов ───────────────────────────────────────────
_VERSION_QUERY_TEMPLATES = [
    "latest version {name}",
    "{name} latest release",
    "{name} release notes",
    "{name} changelog",
    "current {name} version",
    "{name} github releases",
    "{name} новая версия",
    "последняя версия {name}",
]

# ── Приоритет доменов: url-подстрока → бонус/штраф ──────────────────────
# Высокий приоритет: официальные источники, release-страницы, тех-СМИ
_DOMAIN_HIGH: dict = {
    # Страницы релизов (путь содержит releases/changelog)
    "/releases":            +90,
    "/changelog":           +85,
    "/release-notes":       +85,
    "/releasenotes":        +80,
    "/whats-new":           +75,
    "/downloads":           +60,
    # Официальные домены
    "github.com":           +70,
    "gitlab.com":           +65,
    "developer.apple.com":  +85,
    "developer.android.com":+85,
    "developer.chrome.com": +80,
    "docs.python.org":      +85,
    "python.org":           +75,
    "nodejs.org":           +75,
    "rust-lang.org":        +75,
    "golang.org":           +75,
    "kernel.org":           +80,
    "docs.microsoft.com":   +75,
    "learn.microsoft.com":  +70,
    "developer.mozilla.org":+80,
    "huggingface.co":       +65,
    "pytorch.org":          +70,
    "tensorflow.org":       +70,
    # Крупные тех-СМИ с датами
    "techradar.com":        +40,
    "arstechnica.com":      +45,
    "theverge.com":         +35,
    "zdnet.com":            +35,
    "9to5mac.com":          +40,
    "macrumors.com":        +40,
    "androidauthority.com": +40,
    "xda-developers.com":   +35,
    "theregister.com":      +40,
    "habr.com":             +40,
    "ixbt.com":             +35,
    "3dnews.ru":            +30,
    "cnews.ru":             +30,
}

# Низкий приоритет: форумы, агрегаторы, магазины, блоги без дат
_DOMAIN_LOW: dict = {
    "reddit.com":           -25,
    "quora.com":            -30,
    "yahoo.com":            -25,
    "answers.":             -30,
    "forum.":               -25,
    "forums.":              -25,
    "community.":           -20,
    "discussion.":          -20,
    "amazon.com":           -50,
    "ebay.com":             -50,
    "aliexpress.com":       -60,
    "play.google.com":      -40,
    "apps.apple.com":       -40,
    "facebook.com":         -60,
    "instagram.com":        -60,
    "twitter.com":          -35,
    "x.com":                -35,
    "youtube.com":          -40,
    "buzzfeed.com":         -60,
    "pinterest.com":        -60,
    "medium.com":           -10,  # небольшой штраф — может быть полезен
}

# ── Паттерны извлечения версий ───────────────────────────────────────────
import re as _re_vp
import datetime as _dt_vp

_VER_PATS = [
    # Явная метка: Version 17.4.1 / v3.12 / Ver. 3.12
    _re_vp.compile(
        r'(?:version|ver\.?|v)\s*(\d{1,3}\.\d{1,3}(?:\.\d{1,4})?(?:\.\d{1,4})?)',
        _re_vp.IGNORECASE),
    # В скобках: (3.12.1)
    _re_vp.compile(r'\((\d{1,3}\.\d{1,3}(?:\.\d{1,4})?)\)'),
    # Bare X.Y.Z
    _re_vp.compile(r'\b(\d{1,3}\.\d{1,3}(?:\.\d{1,4})?(?:\.\d{1,4})?)\b'),
]

_BETA_PAT   = _re_vp.compile(r'\b(?:beta|b\d+|preview|rc\d*|alpha|dev|nightly)\b',
                               _re_vp.IGNORECASE)
_STABLE_PAT = _re_vp.compile(r'\b(?:stable|release|final|lts|ga|general.availability)\b',
                               _re_vp.IGNORECASE)

# ── Паттерны дат ─────────────────────────────────────────────────────────
_DATE_PATS = [
    _re_vp.compile(r'(202\d)[.\-/](\d{2})[.\-/](\d{2})'),                  # 2024-05-13
    _re_vp.compile(r'(\d{1,2})[.\-/ ](\d{1,2})[.\-/ ](202\d)'),           # 13.05.2024
    _re_vp.compile(
        r'(?:january|february|march|april|may|june|july|august|september|'
        r'october|november|december|январ\w*|феврал\w*|март\w*|апрел\w*|'
        r'май|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)'
        r'\s+\d{1,2}[,\s]+?(202\d)', _re_vp.IGNORECASE),                   # May 13, 2024
    _re_vp.compile(r'\b(202\d)\b'),                                         # запасной: год
]

# Changelog-триггеры
_CHANGELOG_TRIGGER = _re_vp.compile(
    r"(?:what.?s new|changelog|release notes|изменения|что нового|новое в|"
    r"новшества|обновления|улучшения)\b",
    _re_vp.IGNORECASE)

_CHANGELOG_LINE = _re_vp.compile(r'(?:^|[-•*·▪])\s*(.{20,150}?)(?:\n|$)',
                                   _re_vp.MULTILINE)


# ───────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ───────────────────────────────────────────────────────────────────────────

def is_version_query(query: str) -> bool:
    """
    Определяет, является ли запрос запросом о версии ПО.
    Использует два уровня проверки:
    1. Точные фразы (multi-word) — высокая точность.
    2. Одиночные слова-маркеры — ловят «latest X», «X release», «X changelog».
    """
    import re as _re_iq
    q = query.lower()

    # Уровень 1: точные фразы
    if any(kw in q for kw in _VERSION_INTENT_KEYWORDS):
        return True

    # Уровень 2: одиночные маркеры версий
    _SINGLE_MARKERS = [
        r"\blatest\b", r"\bchangelog\b", r"\brelease\b",
        r"\brelease\s+notes\b", r"\bdownload\b",
        r"\bрелиз\b", r"\bверсия\b", r"\bchangelog\b",
        r"\bv\d+\.\d+\b",            # vX.Y в запросе
        r"\d+\.\d+\.\d+\b",         # X.Y.Z в запросе
        r"\bwhat.?s new\b",
    ]
    return any(_re_iq.search(p, q) for p in _SINGLE_MARKERS)


def _vp_domain_score(url: str) -> int:
    """Вычисляет приоритетный балл URL на основе домена и пути."""
    u = url.lower()
    score = 0
    for pattern, pts in _DOMAIN_HIGH.items():
        if pattern in u:
            score = max(score, pts)
    for pattern, pts in _DOMAIN_LOW.items():
        if pattern in u:
            score += pts
    return score


def _vp_parse_ver(v: str) -> tuple:
    """Конвертирует строку версии в сортируемый кортеж."""
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _vp_classify(version: str, context: str) -> str:
    """Определяет тип релиза: stable / beta / rc / alpha."""
    combined = (version + " " + context[:300]).lower()
    if _BETA_PAT.search(combined):
        if "rc" in combined:
            return "rc"
        if "alpha" in combined:
            return "alpha"
        return "beta"
    return "stable"


def _vp_extract_date(text: str) -> str:
    """Извлекает первую читаемую дату из текста страницы."""
    for pat in _DATE_PATS:
        m = pat.search(text)
        if m:
            return m.group(0)[:30].strip()
    return ""


def _vp_extract_software_name(query: str) -> str:
    """
    Извлекает название ПО из запроса.
    «последняя версия Python 3» → «Python 3»
    «что нового в iOS 18» → «iOS 18»
    «latest Firefox release» → «Firefox»
    """
    q = query.strip()
    strip_pats = [
        r'\b(?:последняя|последний|актуальная|актуальный|новая|новый)\s+'
        r'(?:версия|релиз|обновление|release|version)?\s*',
        r'\b(?:что нового в|changelog|release notes|изменения в|список изменений в)\s*',
        r'\b(?:latest|current|newest|recent)\s+(?:version|release|update)?\s*',
        r'\b(?:version|release|update)\s+of\s+',
        r'\b(?:версия|релиз|обновление)\s+',
    ]
    result = q
    for pat in strip_pats:
        result = _re_vp.sub(pat, '', result, flags=_re_vp.IGNORECASE).strip()
    words = result.split()
    # берём до 3 слов — название обычно короткое
    return " ".join(words[:3]) if words else q[:40]


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 1 — SEARCH: несколько поисковых запросов
# ───────────────────────────────────────────────────────────────────────────

def vp_search(
    sw_name: str,
    region: str = "wt-wt",
    language: str = "russian",
    num_per_query: int = 5,
) -> list:
    """
    Выполняет 5 поисковых запросов по шаблонам и собирает уникальные URL.

    Аргументы:
        sw_name:       название ПО (например «Python», «iOS 18», «Firefox»)
        region:        регион поиска
        language:      язык
        num_per_query: результатов за запрос

    Возвращает список уникальных URL (минимум 5–8 источников).
    """
    print(f"[VP:SEARCH] 🔍 Мульти-поиск для «{sw_name}»")
    seen: set = set()
    all_urls: list = []

    for tmpl in _VERSION_QUERY_TEMPLATES[:6]:          # берём 6 из 8 шаблонов
        q = tmpl.format(name=sw_name)
        print(f"[VP:SEARCH]   → {q}")
        try:
            raw = google_search(q, num_results=num_per_query,
                                region=region, language=language)
            for url in _re_vp.findall(r'Ссылка: (https?://[^\s]+)', raw):
                if url not in seen:
                    seen.add(url)
                    all_urls.append(url)
        except Exception as exc:
            print(f"[VP:SEARCH]   ⚠️ Ошибка запроса: {exc}")

    print(f"[VP:SEARCH] ✅ Уникальных URL: {len(all_urls)}")
    return all_urls


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 2 — FILTER: приоритизация, загрузка, фильтр релевантности
# ───────────────────────────────────────────────────────────────────────────

def vp_filter(
    urls: list,
    query: str,
    max_load: int = 8,
) -> list:
    """
    Сортирует URL по приоритету домена, загружает страницы,
    фильтрует нерелевантные через is_relevant_page.

    Повышает приоритет: официальные сайты, /releases, /changelog, GitHub,
    крупные тех-СМИ с датами.
    Понижает приоритет: форумы, агрегаторы, магазины, соцсети.

    Страницы без дат или с текстом < 200 символов отклоняются.

    Аргументы:
        urls:     список URL из vp_search
        query:    исходный запрос (для is_relevant_page)
        max_load: максимум страниц для загрузки

    Возвращает список dict{'url','content','priority','rel_score'}.
    """
    # Сортируем по приоритету
    ranked = sorted([(u, _vp_domain_score(u)) for u in urls],
                    key=lambda x: x[1], reverse=True)
    print(f"[VP:FILTER] Загрузка страниц (топ по приоритету)...")
    pages = []

    for url, priority in ranked:
        if len(pages) >= max_load:
            break

        print(f"[VP:FILTER]  {priority:+4d}  {url[:70]}")
        try:
            text = fetch_page_content(url, max_chars=4000)
        except Exception as exc:
            print(f"[VP:FILTER]   ⚠️ Ошибка загрузки: {exc}")
            continue

        if not text or "[Ошибка" in text or len(text) < 200:
            print(f"[VP:FILTER]   ❌ Слишком короткий или ошибка ({len(text or '')} символов)")
            continue

        # Фильтр релевантности (URL-блокировка + ключевые слова + тема)
        ok, scores, reason = is_relevant_page(query, text, url=url)
        if not ok:
            print(f"[VP:FILTER]   ❌ Нерелевантна: {reason}")
            continue

        pages.append({
            "url":       url,
            "content":   text,
            "priority":  priority,
            "rel_score": scores.get("total_score", 0),
        })
        print(f"[VP:FILTER]   ✅ Принята | rel={scores.get('total_score',0):.0f}")

    print(f"[VP:FILTER] Итого страниц: {len(pages)}")
    return pages


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 3 — EXTRACT: версии, даты, changelog
# ───────────────────────────────────────────────────────────────────────────

def vp_extract(pages: list) -> dict:
    """
    Извлекает из текстов всех страниц:
    - все версии с типом (stable/beta/rc/alpha) и источниками
    - даты публикации каждой страницы
    - фрагменты changelog / release notes

    Аргументы:
        pages: список dict из vp_filter

    Возвращает dict:
    {
        "versions":   [{"version", "type", "date", "sources", "source_count", "priority_sum"}, ...],
        "changelogs": {url: [строка, ...]},
        "dates":      {url: str},
    }
    """
    ver_map: dict = {}
    changelogs: dict = {}
    dates: dict = {}

    for page in pages:
        url      = page["url"]
        text     = page["content"]
        priority = page.get("priority", 0)

        # Дата страницы
        page_date = _vp_extract_date(text)
        dates[url] = page_date

        # ── Извлекаем версии ─────────────────────────────────────────
        found_in_page: set = set()
        for vpat in _VER_PATS:
            for m in vpat.finditer(text):
                v = m.group(1)
                parts = v.split(".")
                if len(parts) < 2:
                    continue
                try:
                    major = int(parts[0])
                except ValueError:
                    continue
                # Фильтр: не IP, не год, не слишком большие числа
                if major < 0 or major > 999:
                    continue
                if 2000 <= major <= 2040:
                    continue   # это год
                if v in found_in_page:
                    continue
                found_in_page.add(v)

                # Контекст для определения типа релиза
                ctx = text[max(0, m.start()-100): m.end()+100]
                rtype = _vp_classify(v, ctx)

                if v not in ver_map:
                    ver_map[v] = {
                        "version":      v,
                        "type":         rtype,
                        "date":         page_date,
                        "sources":      [url],
                        "source_count": 1,
                        "priority_sum": priority,
                    }
                else:
                    info = ver_map[v]
                    if url not in info["sources"]:
                        info["sources"].append(url)
                        info["source_count"] += 1
                        info["priority_sum"] += priority
                    # Уточняем тип
                    if rtype in ("rc", "beta", "alpha") and info["type"] == "stable":
                        info["type"] = rtype
                    if page_date and not info["date"]:
                        info["date"] = page_date

        # ── Changelog-фрагменты ──────────────────────────────────────
        trigger = _CHANGELOG_TRIGGER.search(text)
        if trigger:
            block = text[trigger.end(): trigger.end() + 2500]
            lines = [m.group(1).strip()
                     for m in _CHANGELOG_LINE.finditer(block)
                     if len(m.group(1).strip()) > 20]
            if lines:
                changelogs[url] = lines[:10]

    return {
        "versions":   list(ver_map.values()),
        "changelogs": changelogs,
        "dates":      dates,
    }


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 4 — VALIDATE: консенсус версий, уровень доверия
# ───────────────────────────────────────────────────────────────────────────

def vp_validate(extracted: dict, max_age_months: int = 18) -> dict:
    """
    Проверяет актуальность версий и выбирает консенсусную.

    Логика:
    - Сортирует версии по номеру (от новейшей к старейшей).
    - Stable-версия с подтверждением ≥ 2 источников — выбирается как лучшая.
    - Pre-release (beta/rc/alpha) выбирается если новее stable.
    - Уровень доверия: high (≥3 источника), medium (≥2), low (<2).
    - Если top-3 версии из разных мажорных веток — генерируется предупреждение.

    Аргументы:
        extracted:      dict из vp_extract()
        max_age_months: порог устаревания источников (пока информационный)

    Возвращает dict:
    {
        "stable":        dict | None,   # лучшая стабильная версия
        "pre_release":   dict | None,   # лучшая бета/RC (если новее stable)
        "all_stable":    list,          # все stable, отсортированные
        "changelogs":    dict,
        "confidence":    "high"|"medium"|"low",
        "warning":       str,           # "" если нет предупреждений
    }
    """
    versions  = extracted.get("versions", [])
    changelogs = extracted.get("changelogs", {})

    if not versions:
        return {
            "stable":       None,
            "pre_release":  None,
            "all_stable":   [],
            "changelogs":   changelogs,
            "confidence":   "low",
            "warning":      "Не удалось извлечь версии из источников.",
        }

    # Сортируем всё по номеру версии
    all_sorted = sorted(versions, key=lambda v: _vp_parse_ver(v["version"]),
                        reverse=True)

    stable_vers  = [v for v in all_sorted if v["type"] == "stable"]
    pre_rel_vers = [v for v in all_sorted if v["type"] in ("beta", "rc", "alpha")]

    # ── Лучшая stable-версия ────────────────────────────────────────
    # Предпочитаем подтверждённую ≥2 источниками
    confirmed = [v for v in stable_vers if v["source_count"] >= 2]
    best_stable = confirmed[0] if confirmed else (stable_vers[0] if stable_vers else None)

    # ── Лучшая pre-release ─────────────────────────────────────────
    best_pre = None
    if pre_rel_vers:
        candidate = pre_rel_vers[0]
        if best_stable is None or (
            _vp_parse_ver(candidate["version"]) > _vp_parse_ver(best_stable["version"])
        ):
            best_pre = candidate

    # ── Доверие ──────────────────────────────────────────────────────
    if best_stable and best_stable["source_count"] >= 3:
        confidence = "high"
    elif best_stable and best_stable["source_count"] >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    # ── Предупреждение о разбросе версий ────────────────────────────
    warning = ""
    top3 = [v["version"] for v in stable_vers[:3]]
    if len(top3) >= 2:
        try:
            tuples = [_vp_parse_ver(v) for v in top3]
            if tuples[0][0] != tuples[-1][0]:
                warning = (
                    f"Найдены версии из разных мажорных веток: {', '.join(top3)}. "
                    f"Рекомендую уточнить на официальном сайте разработчика."
                )
        except Exception:
            pass

    return {
        "stable":       best_stable,
        "pre_release":  best_pre,
        "all_stable":   stable_vers[:8],
        "changelogs":   changelogs,
        "confidence":   confidence,
        "warning":      warning,
    }


# ───────────────────────────────────────────────────────────────────────────
# ШАГ 5 — ANSWER: форматирование результата для промпта
# ───────────────────────────────────────────────────────────────────────────

def vp_answer(
    validated: dict,
    pages: list,
    sw_name: str,
    detected_language: str = "russian",
) -> str:
    """
    Формирует строку-контекст для передачи в промпт AI.

    Содержит:
    - последнюю стабильную версию + дату + источники
    - последнюю бета/RC (если есть)
    - список изменений из changelog-блоков
    - все использованные источники
    - предупреждение об уровне доверия
    - явные правила для AI (не придумывать, не обобщать без источника)

    Аргументы:
        validated:         dict из vp_validate()
        pages:             список страниц из vp_filter()
        sw_name:           название ПО
        detected_language: "russian" или иное (→ английский)
    """
    is_ru   = detected_language == "russian"
    SEP     = "═" * 56
    lines   = []

    stable    = validated.get("stable")
    pre_rel   = validated.get("pre_release")
    confidence = validated.get("confidence", "low")
    warning   = validated.get("warning", "")
    changelogs = validated.get("changelogs", {})

    conf_label = {"high": "🟢 ВЫСОКИЙ", "medium": "🟡 СРЕДНИЙ",
                  "low":  "🔴 НИЗКИЙ"}.get(confidence, confidence)

    if is_ru:
        lines += [SEP,
                  f"📦 ДАННЫЕ О ВЕРСИИ: {sw_name.upper()}",
                  f"Достоверность: {conf_label}",
                  SEP]
    else:
        lines += [SEP,
                  f"📦 VERSION DATA: {sw_name.upper()}",
                  f"Confidence: {conf_label}",
                  SEP]

    # ── Stable ───────────────────────────────────────────────────────
    if stable:
        ver  = stable["version"]
        date = stable.get("date") or ("неизвестна" if is_ru else "unknown")
        cnt  = stable.get("source_count", 1)
        srcs = stable.get("sources", [])[:3]
        if is_ru:
            lines += ["",
                      f"✅ ПОСЛЕДНЯЯ СТАБИЛЬНАЯ ВЕРСИЯ: {ver}",
                      f"   Дата выхода: {date}",
                      f"   Подтверждена в {cnt} источнике(ах):"]
        else:
            lines += ["",
                      f"✅ LATEST STABLE VERSION: {ver}",
                      f"   Release date: {date}",
                      f"   Confirmed in {cnt} source(s):"]
        for s in srcs:
            lines.append(f"      • {s[:70]}")
    else:
        lines.append("\n⚠️ " + ("Стабильная версия не определена." if is_ru
                                 else "Stable version not determined."))

    # ── Pre-release ──────────────────────────────────────────────────
    if pre_rel:
        ver   = pre_rel["version"]
        rtype = pre_rel.get("type", "beta").upper()
        date  = pre_rel.get("date") or ("неизвестна" if is_ru else "unknown")
        cnt   = pre_rel.get("source_count", 1)
        if is_ru:
            lines += ["",
                      f"🧪 ПОСЛЕДНЯЯ {rtype}-ВЕРСИЯ: {ver}",
                      f"   Дата: {date} | Источников: {cnt}"]
        else:
            lines += ["",
                      f"🧪 LATEST {rtype}: {ver}",
                      f"   Date: {date} | Sources: {cnt}"]

    # ── Все найденные stable-версии ─────────────────────────────────
    all_stable = validated.get("all_stable", [])
    if len(all_stable) > 1:
        ver_list = ", ".join(v["version"] for v in all_stable[:5])
        if is_ru:
            lines.append(f"\n   Все найденные стабильные версии: {ver_list}")
        else:
            lines.append(f"\n   All found stable versions: {ver_list}")

    # ── Changelog ───────────────────────────────────────────────────
    if changelogs:
        # Берём лог из источника с наивысшим приоритетом
        best_url = max(changelogs, key=lambda u: _vp_domain_score(u))
        cl_lines = changelogs[best_url][:8]
        label = "📋 ИЗМЕНЕНИЯ (из источника):" if is_ru else "📋 CHANGES (from source):"
        lines.append(f"\n{label}")
        lines.append(f"   Источник: {best_url[:70]}")
        for cl in cl_lines:
            lines.append(f"   • {cl}")
    else:
        lines.append("\n" + ("📋 Блок изменений не найден в загруженных источниках."
                              if is_ru else "📋 No changelog block found in loaded sources."))

    # ── Источники ────────────────────────────────────────────────────
    used = [p["url"] for p in pages[:6]]
    lines.append("\n" + ("🔗 ИСПОЛЬЗОВАННЫЕ ИСТОЧНИКИ:" if is_ru else "🔗 SOURCES USED:"))
    for i, u in enumerate(used, 1):
        prio = _vp_domain_score(u)
        tier = ("✅" if prio >= 50 else "⚪" if prio >= 0 else "⚠️")
        lines.append(f"   {i}. {tier} {u[:80]}")

    # ── Предупреждения ───────────────────────────────────────────────
    if warning:
        lines.append(f"\n⚠️  {warning}")

    if confidence == "low":
        low_msg = (
            "⚠️  ВНИМАНИЕ: Низкая достоверность — версия подтверждена менее чем 2 независимыми "
            "источниками. Настоятельно рекомендую проверить на официальном сайте."
            if is_ru else
            "⚠️  WARNING: Low confidence — version confirmed by fewer than 2 independent sources. "
            "Please verify on the official website."
        )
        lines.append(f"\n{low_msg}")

    # ── Правила для AI (запрет галлюцинаций) ────────────────────────
    if is_ru:
        lines += [
            "",
            SEP,
            "🚫 ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ДЛЯ AI:",
            "   • Используй ТОЛЬКО данные из блока выше — ничего сверх этого",
            "   • НЕ придумывай список изменений и новые функции",
            "   • НЕ пиши «улучшена стабильность» или другие общие фразы без источника",
            "   • Если данных нет — прямо скажи об этом пользователю",
            "   • Если достоверность LOW или MEDIUM — обязательно предупреди пользователя",
            "   • Всегда указывай источники в ответе",
            SEP,
        ]
    else:
        lines += [
            "",
            SEP,
            "🚫 MANDATORY AI RULES:",
            "   • Use ONLY the data from the block above — nothing beyond it",
            "   • Do NOT invent change lists or new features",
            "   • Do NOT write vague phrases like 'improved stability' without a source",
            "   • If data is missing — tell the user directly",
            "   • If confidence is LOW or MEDIUM — always warn the user",
            "   • Always cite sources in your answer",
            SEP,
        ]

    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────────────
# ОРКЕСТРАТОР — version_search_pipeline
# ───────────────────────────────────────────────────────────────────────────

def version_search_pipeline(
    user_query: str,
    region: str = "wt-wt",
    language: str = "russian",
) -> tuple:
    """
    Полный модульный пайплайн для определения актуальной версии ПО.

    Архитектура: search → filter → extract → validate → answer

    Шаги:
    1. vp_search    — 6 поисковых запросов по шаблонам, 5–8 источников
    2. vp_filter    — приоритизация по домену, загрузка, фильтр релевантности
    3. vp_extract   — извлечение версий, дат, changelog из всех страниц
    4. vp_validate  — консенсус версий, уровень доверия, предупреждения
    5. vp_answer    — форматированный блок с запретом галлюцинаций

    Аргументы:
        user_query: исходный запрос пользователя
        region:     регион поиска
        language:   язык результатов

    Возвращает КОРТЕЖ (result_str: str, page_contents: list):
        result_str    — форматированный блок данных для передачи в промпт
        page_contents — список загруженных страниц dict{'url','content',...}
    """
    print(f"[VP:PIPELINE] ════ СТАРТ ПАЙПЛАЙНА ВЕРСИЙ ════")
    print(f"[VP:PIPELINE] Запрос: {user_query}")

    # ── Определяем название ПО ───────────────────────────────────────
    sw_name = _vp_extract_software_name(user_query)
    print(f"[VP:PIPELINE] 📦 Название ПО: «{sw_name}»")

    # ── 1. SEARCH ────────────────────────────────────────────────────
    urls = vp_search(sw_name, region=region, language=language, num_per_query=5)
    if not urls:
        msg = "⚠️ Поиск не вернул результатов." if language == "russian" \
              else "⚠️ Search returned no results."
        return msg, []

    # ── 2. FILTER ────────────────────────────────────────────────────
    pages = vp_filter(urls, query=user_query, max_load=8)
    if not pages:
        msg = ("⚠️ Подходящих источников не найдено после фильтрации." if language == "russian"
               else "⚠️ No suitable sources found after filtering.")
        return msg, []

    # ── 3. EXTRACT ───────────────────────────────────────────────────
    extracted = vp_extract(pages)
    n_versions = len(extracted["versions"])
    print(f"[VP:PIPELINE] 🔢 Извлечено версий: {n_versions} | "
          f"с changelog: {len(extracted['changelogs'])}")

    # Если не нашли ни одной версии — откатываемся к обычному поиску
    if n_versions == 0:
        print(f"[VP:PIPELINE] ⚠️ Версии не найдены, передаём страницы как есть")
        fallback_str = "\n\n".join(
            f"[Источник {i+1}]\nURL: {p['url']}\n{p['content'][:1500]}"
            for i, p in enumerate(pages[:4])
        )
        return fallback_str, pages

    # ── 4. VALIDATE ──────────────────────────────────────────────────
    validated = vp_validate(extracted, max_age_months=18)
    stable = validated["stable"]
    if stable:
        print(f"[VP:PIPELINE] ✅ Stable: {stable['version']} "
              f"(источников: {stable['source_count']}, "
              f"доверие: {validated['confidence']})")
    else:
        print(f"[VP:PIPELINE] ⚠️ Стабильная версия не определена")

    # ── 5. ANSWER ────────────────────────────────────────────────────
    result_str = vp_answer(validated, pages, sw_name, language)
    print(f"[VP:PIPELINE] ✓ Завершён. Страниц: {len(pages)}, "
          f"символов в контексте: {len(result_str)}")

    return result_str, pages

def deep_web_search(
    query: str,
    num_results: int = 5,
    region: str = "wt-wt",
    language: str = "russian",
    max_pages: int = 3,
) -> tuple:
    """
    Глубокий веб-поиск с полным пайплайном качества.

    Пайплайн:
    1. Первичный поиск (DuckDuckGo)
    2. Загрузка страниц + фильтр релевантности (is_relevant_page)
    3. Фильтр свежести + наличия фактов (filter_pages)
    4. Оценка качества источников (source_quality_score)
       → сортировка, выбор топ-3 лучших
       → если качественных < 2: автоматический повторный поиск
    5. Финальный retry_search_if_needed если всё ещё мало источников

    Возвращает КОРТЕЖ (result_str: str, page_contents: list):
      - result_str    — текстовый блок для передачи в промпт
      - page_contents — список dict с добавленным 'quality_score'
    """
    print(f"[DEEP_SEARCH] ═══ ЗАПУСК ГЛУБОКОГО ВЕБ-ПОИСКА ═══")
    print(f"[DEEP_SEARCH] Запрос: {query}")

    # ── ШАГ 1: Первичный поиск ──────────────────────────────────────
    search_results = google_search(query, num_results, region, language)

    if "Ничего не найдено" in search_results or "Ошибка" in search_results:
        return search_results, []

    import re
    urls = re.findall(r'Ссылка: (https?://[^\s]+)', search_results)

    if not urls:
        print(f"[DEEP_SEARCH] ⚠️ URL не найдены в результатах")
        return search_results, []

    print(f"[DEEP_SEARCH] Найдено {len(urls)} URL для анализа")

    # ── ШАГ 2: Загрузка + фильтр релевантности ──────────────────────
    effective_max = min(max(max_pages, 5), len(urls))  # берём чуть больше для отбора
    raw_pages = []

    for i, url in enumerate(urls[:effective_max], 1):
        print(f"[DEEP_SEARCH] Загрузка страницы {i}/{effective_max}...")
        page_text = fetch_page_content(url, max_chars=3000)

        if page_text and "[Ошибка" not in page_text:
            is_ok, scores, reason = is_relevant_page(query, page_text, url=url)
            if is_ok:
                raw_pages.append({
                    "url": url,
                    "content": page_text,
                    "relevance_score": scores.get("total_score", 0),
                })
                print(f"[DEEP_SEARCH] ✅ Страница {i} релевантна "
                      f"(total={scores.get('total_score',0):.0f})")
            else:
                print(f"[DEEP_SEARCH] ❌ Страница {i} ОТКЛОНЕНА: {reason}")
        else:
            print(f"[DEEP_SEARCH] ⚠️ Страница {i}: ошибка загрузки")

    # ── ШАГ 3: Свежесть + факты ─────────────────────────────────────
    fresh_pages = filter_pages(raw_pages, query)

    # ── ШАГ 4: Оценка качества + сортировка + retry ─────────────────
    print(f"[DEEP_SEARCH] 🔍 Оцениваю качество {len(fresh_pages)} источников...")
    quality_pages, needs_quality_retry = rank_and_select_sources(
        fresh_pages, query, top_n=3, min_quality_score=20.0, min_sources=2
    )

    if needs_quality_retry:
        print(f"[DEEP_SEARCH] 🔄 Недостаточно качественных источников, "
              f"запускаю повторный поиск...")
        quality_pages = retry_search_if_needed(
            quality_pages,
            query,
            num_results=num_results,
            region=region,
            language=language,
            max_pages=max_pages,
            min_good_sources=2,
        )
        # После retry — снова оцениваем и сортируем
        if quality_pages:
            quality_pages, _ = rank_and_select_sources(
                quality_pages, query, top_n=3, min_quality_score=5.0
            )

    page_contents = quality_pages

    if not page_contents:
        print(f"[DEEP_SEARCH] ⚠️ Подходящих страниц нет, возвращаю базовые результаты")
        return search_results, []

    # ── ШАГ 5: Формируем текстовый блок для промпта ─────────────────
    enhanced_results = search_results + "\n\n" + "═" * 60 + "\n"
    enhanced_results += "📄 СОДЕРЖИМОЕ ПРОАНАЛИЗИРОВАННЫХ СТРАНИЦ:\n"
    enhanced_results += "═" * 60 + "\n\n"

    for i, page in enumerate(page_contents, 1):
        q_score = page.get("quality_score", 0)
        tier    = page.get("quality_detail", {}).get("tier", "")
        enhanced_results += f"[Источник {i} | качество: {q_score:.0f}пт | {tier}]\n"
        enhanced_results += f"URL: {page['url']}\n"
        enhanced_results += f"Текст: {page['content']}\n\n"
        enhanced_results += "-" * 60 + "\n\n"

    print(f"[DEEP_SEARCH] ✓ Завершён. "
          f"Лучших источников: {len(page_contents)}, "
          f"объём: {len(enhanced_results)} символов")

    return enhanced_results, page_contents

def fallback_web_search(query: str, num_results: int = 5, language: str = "russian") -> str:
    """Fallback веб-поиск через DuckDuckGo HTML без внешних библиотек"""
    print(f"[FALLBACK_SEARCH] Запуск fallback поиска для: {query}")
    
    try:
        import urllib.parse
        import re
        from html import unescape
        
        # Формируем URL для DuckDuckGo
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        
        # Настраиваем заголовки чтобы выглядеть как браузер
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7' if language == "russian" else 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        print(f"[FALLBACK_SEARCH] Отправка запроса к DuckDuckGo...")
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        html_content = response.text
        print(f"[FALLBACK_SEARCH] Получен HTML, длина: {len(html_content)} символов")
        
        # Парсим результаты с помощью регулярных выражений
        # DuckDuckGo HTML использует структуру: <div class="result">
        
        # Ищем заголовки результатов
        title_pattern = r'<a[^>]*class="result__a"[^>]*>([^<]+)</a>'
        titles = re.findall(title_pattern, html_content)
        
        # Ищем описания
        snippet_pattern = r'<a[^>]*class="result__snippet"[^>]*>([^<]+)</a>'
        snippets = re.findall(snippet_pattern, html_content)
        
        # Ищем ссылки
        url_pattern = r'<a[^>]*class="result__url"[^>]*href="([^"]+)"'
        urls = re.findall(url_pattern, html_content)
        
        # Если стандартный паттерн не сработал, пробуем альтернативный
        if not titles:
            print(f"[FALLBACK_SEARCH] Стандартный паттерн не сработал, пробуем альтернативный...")
            # Альтернативный паттерн для нового формата DuckDuckGo
            title_pattern = r'class="result__title"[^>]*><a[^>]*>(.+?)</a>'
            titles = re.findall(title_pattern, html_content, re.DOTALL)
            
            snippet_pattern = r'class="result__snippet">(.+?)</div>'
            snippets = re.findall(snippet_pattern, html_content, re.DOTALL)
        
        print(f"[FALLBACK_SEARCH] Найдено: заголовков={len(titles)}, описаний={len(snippets)}, ссылок={len(urls)}")
        
        if not titles and not snippets:
            print(f"[FALLBACK_SEARCH] Не удалось распарсить результаты. Возможно, изменился формат DuckDuckGo.")
            return "⚠️ Не удалось получить результаты поиска. Попробуйте установить библиотеку: pip install ddgs"
        
        # Объединяем результаты
        search_results = []
        for i in range(min(num_results, len(titles))):
            title = unescape(re.sub(r'<[^>]+>', '', titles[i])).strip() if i < len(titles) else "Без заголовка"
            snippet = unescape(re.sub(r'<[^>]+>', '', snippets[i])).strip() if i < len(snippets) else "Нет описания"
            url = urls[i] if i < len(urls) else ""
            
            # Декодируем URL если он закодирован
            if url.startswith('//duckduckgo.com/l/?'):
                # Извлекаем реальный URL из redirect
                url_match = re.search(r'uddg=([^&]+)', url)
                if url_match:
                    url = urllib.parse.unquote(url_match.group(1))
            
            search_results.append(
                f"[Результат {i+1}]\n"
                f"Заголовок: {title}\n"
                f"Описание: {snippet}\n"
                f"Ссылка: {url}"
            )
            print(f"[FALLBACK_SEARCH] Результат {i+1}: {title[:50]}...")
        
        if not search_results:
            return "⚠️ Результаты поиска пусты. Попробуйте переформулировать запрос."
        
        final_results = "\n\n".join(search_results)
        print(f"[FALLBACK_SEARCH] ✓ Fallback поиск завершён. Найдено {len(search_results)} результатов")
        return final_results
        
    except requests.Timeout:
        return "⚠️ Превышено время ожидания ответа от поисковика. Попробуйте снова."
    except requests.RequestException as e:
        return f"⚠️ Ошибка сетевого подключения: {e}"
    except Exception as e:
        print(f"[FALLBACK_SEARCH] ✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return f"⚠️ Ошибка fallback поиска: {e}"

# -------------------------
# TTS с pyttsx3
# -------------------------
def compress_search_results(search_results: str, max_length: int) -> str:
    """Сжимает результаты поиска до нужной длины, сохраняя самое важное"""
    print(f"[COMPRESS] Начальная длина: {len(search_results)} символов")
    print(f"[COMPRESS] Целевая длина: {max_length} символов")
    
    if len(search_results) <= max_length:
        print(f"[COMPRESS] Сжатие не требуется")
        return search_results
    
    # Разбиваем на отдельные результаты
    results = search_results.split('[Результат ')
    if len(results) <= 1:
        # Если не удалось разбить, просто обрезаем
        print(f"[COMPRESS] Простое обрезание до {max_length} символов")
        return search_results[:max_length] + "..."
    
    # Первый элемент - пустой, убираем
    results = results[1:]
    
    # Вычисляем, сколько символов на каждый результат
    chars_per_result = max_length // len(results)
    print(f"[COMPRESS] Результатов: {len(results)}, символов на результат: {chars_per_result}")
    
    compressed_results = []
    for i, result in enumerate(results, 1):
        # Восстанавливаем структуру
        result = '[Результат ' + result
        
        # Извлекаем основные части
        lines = result.split('\n')
        title_line = ""
        description_line = ""
        link_line = ""
        
        for line in lines:
            if line.startswith('Заголовок:'):
                title_line = line
            elif line.startswith('Описание:'):
                description_line = line
            elif line.startswith('Ссылка:'):
                link_line = line
        
        # Сжимаем описание, если нужно
        if description_line:
            desc_prefix = "Описание: "
            desc_text = description_line[len(desc_prefix):]
            
            # Оставляем место для заголовка и ссылки (примерно 200 символов)
            available_for_desc = chars_per_result - 200
            if available_for_desc < 100:
                available_for_desc = 100
            
            if len(desc_text) > available_for_desc:
                desc_text = desc_text[:available_for_desc] + "..."
                description_line = desc_prefix + desc_text
        
        # Собираем сжатый результат
        compressed = f"[Результат {i}]\n{title_line}\n{description_line}\n{link_line}"
        compressed_results.append(compressed)
    
    final_result = "\n\n".join(compressed_results)
    print(f"[COMPRESS] Итоговая длина: {len(final_result)} символов")
    
    return final_result


# ═══════════════════════════════════════════════════════════════════
# ПАЙПЛАЙН ОБРАБОТКИ ОТВЕТА ПОСЛЕ ПОИСКА
# ═══════════════════════════════════════════════════════════════════

def summarize_sources(raw_search_results: str, query: str, detected_language: str = "russian") -> str:
    """
    Вызывает Ollama для извлечения только фактов из сырого содержимого страниц.
    Модели передаётся только сжатый список фактов, а не длинный текст страниц.
    """
    print(f"[SUMMARIZE] Начинаю извлечение фактов из результатов поиска...")

    # Если результаты небольшие — не тратим время на промежуточный вызов
    if len(raw_search_results) < 1500:
        print(f"[SUMMARIZE] Результаты небольшие ({len(raw_search_results)} символов), пропускаем суммаризацию")
        return raw_search_results

    if detected_language == "russian":
        summarize_prompt = f"""Ты — строгий фильтр фактов. Вот содержимое веб-страниц по запросу: "{query}"

{raw_search_results}

ЗАДАЧА: Извлеки ТОЛЬКО факты, которые НАПРЯМУЮ отвечают на запрос "{query}".

СТРОГИЕ ПРАВИЛА:
- ❌ ИГНОРИРУЙ результаты, которые не относятся к теме запроса (реклама, случайные страницы, не по теме)
- ❌ НЕ включай факты о посторонних вещах, даже если они есть в источниках
- ✅ Включай ТОЛЬКО факты, прямо отвечающие на запрос
- Каждый факт — отдельная строка, начинающаяся с "• "
- Максимум 10 фактов
- НЕ копируй целые абзацы — только суть
- НЕ добавляй своих рассуждений
- Если ни один результат не относится к теме — напиши: "Релевантных фактов не найдено"

Отвечай на русском языке."""
    else:
        summarize_prompt = f"""You are a strict fact filter. Here is web page content for query: "{query}"

{raw_search_results}

TASK: Extract ONLY facts that DIRECTLY answer the query "{query}".

STRICT RULES:
- ❌ IGNORE results not related to the query topic (ads, random pages, off-topic)
- ❌ Do NOT include facts about unrelated things, even if they appear in sources
- ✅ Include ONLY facts that directly answer the query
- Each fact on a new line starting with "• "
- Maximum 10 facts
- Do NOT copy full paragraphs — only the core info
- Do NOT add your own reasoning
- If no results are relevant — write: "No relevant facts found"

Answer in English."""

    try:
        payload = {
            "model": get_current_ollama_model(),
            "messages": [{"role": "user", "content": summarize_prompt}],
            "stream": False,
            "options": {"num_predict": 600, "temperature": 0.1}
        }
        response = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=45)
        if response.status_code == 200:
            data = response.json()
            facts = data.get("message", {}).get("content", "").strip()
            if facts and len(facts) > 50:
                print(f"[SUMMARIZE] ✓ Факты извлечены. Длина: {len(facts)} символов")
                return facts
    except Exception as e:
        print(f"[SUMMARIZE] ⚠️ Ошибка при суммаризации: {e}")

    # Если что-то пошло не так — возвращаем оригинал
    print(f"[SUMMARIZE] Возвращаю оригинальные результаты")
    return raw_search_results


def detect_question_parts(query: str) -> dict:
    """
    Определяет структуру вопроса пользователя:
    - есть ли запрос на версию/номер
    - есть ли запрос на изменения/что нового
    - есть ли запрос на объяснение/как работает
    - сколько отдельных вопросов/пунктов
    """
    q = query.lower()

    has_version = any(kw in q for kw in [
        "версия", "version", "v.", "релиз", "release", "обновление", "update",
        "какая версия", "последняя версия", "новая версия", "вышла"
    ])

    has_changes = any(kw in q for kw in [
        "что изменилось", "что нового", "что добавили", "что нового в",
        "изменения", "нововведения", "changelog", "changes", "what's new",
        "что поменялось", "отличия", "отличается", "новые функции", "улучшения"
    ])

    has_explanation = any(kw in q for kw in [
        "как работает", "как", "почему", "зачем", "объясни", "расскажи",
        "what is", "how does", "explain", "why", "что это", "что такое"
    ])

    # Подсчёт пунктов: вопросительные знаки, союзы "и ещё", нумерация
    question_marks = q.count("?")
    has_multiple = (
        question_marks > 1
        or any(kw in q for kw in ["и ещё", "и также", "а также", "плюс", "и ещё", "кроме того", "во-первых", "и как"])
        or (has_version and has_changes)
        or (has_version and has_explanation)
        or (has_changes and has_explanation)
    )

    parts_count = sum([has_version, has_changes, has_explanation])
    if question_marks > 1:
        parts_count = max(parts_count, question_marks)

    result = {
        "has_version": has_version,
        "has_changes": has_changes,
        "has_explanation": has_explanation,
        "has_multiple": has_multiple,
        "parts_count": parts_count
    }
    print(f"[DETECT_PARTS] Анализ вопроса: {result}")
    return result


def detect_language_of_text(text: str) -> str:
    """Определяет язык текста по характерным символам."""
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    if cyrillic > latin:
        return "russian"
    return "english"


def validate_answer(answer: str, query: str, detected_language: str, facts: str = "") -> dict:
    """
    Проверяет качество ответа:
    - язык совпадает с языком пользователя
    - нет вставок на другом языке (более 20% слов другого языка)
    - все части вопроса раскрыты
    - нет явной копипасты из источников (длинные совпадения >80 символов)

    Возвращает: {"valid": bool, "issues": list[str]}
    """
    issues = []
    answer_lower = answer.lower()

    # 1. Проверка языка
    answer_lang = detect_language_of_text(answer)
    if answer_lang != detected_language:
        issues.append(f"wrong_language: ответ на {answer_lang}, ожидается {detected_language}")

    # 2. Проверка смешивания языков
    if detected_language == "russian":
        # Считаем процент латинских слов (исключаем URL и технические термины)
        words = answer.split()
        latin_words = [w for w in words if all('a' <= c.lower() <= 'z' for c in w if c.isalpha()) and len(w) > 3 and 'http' not in w]
        if len(words) > 10 and len(latin_words) / len(words) > 0.25:
            issues.append(f"language_mixing: {len(latin_words)}/{len(words)} слов латинские")

    # 3. Проверка полноты по частям вопроса
    parts = detect_question_parts(query)
    if parts["has_version"] and not any(kw in answer_lower for kw in ["версия", "version", "v.", "релиз", "release", "вышла", "обновлен"]):
        issues.append("missing_version: не упомянута версия/релиз")
    if parts["has_changes"] and not any(kw in answer_lower for kw in ["изменил", "добавил", "нов", "улучшил", "исправил", "change", "new", "update", "feature"]):
        issues.append("missing_changes: не описаны изменения")
    if parts["has_explanation"] and len(answer) < 200:
        issues.append("missing_explanation: объяснение слишком короткое")

    # 4. Проверка копипасты из источников (если переданы факты)
    if facts:
        # Ищем длинные строки (>80 символов), которые есть и в ответе, и в фактах
        sentences = [s.strip() for s in facts.replace('\n', '. ').split('.') if len(s.strip()) > 80]
        for sentence in sentences[:20]:
            # Нормализуем для сравнения
            s_norm = ' '.join(sentence.lower().split())
            a_norm = ' '.join(answer.lower().split())
            if s_norm in a_norm:
                issues.append(f"copy_paste: найдена копипаста из источников")
                break

    valid = len(issues) == 0
    result = {"valid": valid, "issues": issues}
    if not valid:
        print(f"[VALIDATE] ⚠️ Проверка не пройдена: {issues}")
    else:
        print(f"[VALIDATE] ✓ Ответ прошёл проверку")
    return result


def build_final_answer_prompt(user_message: str, facts: str, question_parts: dict, detected_language: str, issues: list = None) -> str:
    """
    Строит финальный промпт для генерации ответа с учётом структуры вопроса.
    Используется при первой генерации и при перегенерации после провала валидации.
    """
    # Инструкции по структуре ответа
    structure_hints = []
    if question_parts["has_version"]:
        if detected_language == "russian":
            structure_hints.append("• Начни с текущей версии/релиза")
        else:
            structure_hints.append("• Start with the current version/release")

    if question_parts["has_changes"]:
        if detected_language == "russian":
            structure_hints.append("• Перечисли изменения списком (каждое изменение — новая строка с «–»)")
        else:
            structure_hints.append("• List changes as bullet points (each change on new line with '–')")

    if question_parts["has_explanation"]:
        if detected_language == "russian":
            structure_hints.append("• Объясни кратко своими словами, не цитируя источники")
        else:
            structure_hints.append("• Briefly explain in your own words, no direct quotes from sources")

    if question_parts["has_multiple"]:
        if detected_language == "russian":
            structure_hints.append("• Ответь на ВСЕ части вопроса последовательно")
        else:
            structure_hints.append("• Answer ALL parts of the question in order")

    structure_block = "\n".join(structure_hints) if structure_hints else ""

    # Блок с исправлениями (при перегенерации)
    fix_block = ""
    if issues:
        if detected_language == "russian":
            fix_block = f"\n\nПРЕДЫДУЩИЙ ОТВЕТ БЫЛ ПЛОХИМ. Проблемы:\n" + "\n".join(f"- {i}" for i in issues) + "\nИСПРАВЬ все эти проблемы в новом ответе.\n"
        else:
            fix_block = f"\n\nPREVIOUS ANSWER WAS REJECTED. Issues:\n" + "\n".join(f"- {i}" for i in issues) + "\nFIX all these issues in the new answer.\n"

    if detected_language == "russian":
        prompt = f"""Ты помогаешь пользователю ответить на вопрос. У тебя есть список фактов из интернета.

ФАКТЫ ИЗ ИСТОЧНИКОВ:
{facts}

ВОПРОС ПОЛЬЗОВАТЕЛЯ:
{user_message}

ТРЕБОВАНИЯ К ОТВЕТУ:
{structure_block}
• Используй ТОЛЬКО факты, которые НАПРЯМУЮ относятся к вопросу пользователя
• ❌ ИГНОРИРУЙ любые факты не по теме (про другие фильмы, города, организации и т.д.)
• Если фактов по теме мало — честно скажи что информации недостаточно, не додумывай
• Пиши связный текст своими словами, не как кусок статьи
• НЕ копируй фразы из источников — перефразируй
• Отвечай ИСКЛЮЧИТЕЛЬНО на русском языке, без английских вставок
• 🚫 НЕ вставляй URL-адреса в текст{fix_block}

Ответ:"""
    else:
        prompt = f"""You are helping the user answer a question. You have a list of facts from the internet.

FACTS FROM SOURCES:
{facts}

USER QUESTION:
{user_message}

ANSWER REQUIREMENTS:
{structure_block}
• Write coherent text, like a normal answer — not a fragment of an article
• Use ONLY facts from the list above, don't invent anything
• Do NOT copy phrases from sources — rephrase in your own words
• Answer EXCLUSIVELY in English, no Russian inserts
• 🚫 Do NOT insert URLs in the text{fix_block}

Answer:"""

    return prompt


def build_contextual_search_query(user_message: str, chat_manager, chat_id: int, detected_language: str) -> str:
    """
    Формирует контекстный поисковый запрос на основе истории диалога.
    
    Логика:
    1. Определяет, является ли вопрос уточняющим (короткий или с ключевыми словами)
    2. Если уточняющий - добавляет контекст из предыдущих сообщений
    3. Если самостоятельный - возвращает как есть
    """
    print(f"[CONTEXTUAL_SEARCH] Анализирую вопрос...")
    print(f"[CONTEXTUAL_SEARCH] Вопрос: {user_message}")
    
    # Получаем последние сообщения для контекста
    if chat_manager and chat_id:
        history = chat_manager.get_chat_messages(chat_id, limit=10)
    else:
        # Fallback на старую БД
        import sqlite3
        conn = sqlite3.connect("chat_memory.db")
        cur = conn.cursor()
        cur.execute("SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT 10")
        history = list(reversed(cur.fetchall()))
        conn.close()
    
    if not history or len(history) < 2:
        print(f"[CONTEXTUAL_SEARCH] История короткая, используем исходный запрос")
        return user_message
    
    # Ключевые слова уточняющих вопросов
    clarifying_keywords_ru = [
        'а почему', 'а как', 'а где', 'а когда', 'а что', 'а кто', 'а после', 'а завтра', 'а вчера', 'а сегодня',
        'почему', 'как именно', 'что именно', 'когда именно', 'где именно',
        'расскажи', 'подробнее', 'ещё', 'еще', 'тоже', 'также', 'дальше',
        'его', 'её', 'их', 'этого', 'этой', 'этим', 'этот', 'эта', 'это',
        'тогда', 'потом', 'после этого', 'что дальше',
        'завтра', 'вчера', 'сегодня', 'послезавтра'  # ВАЖНО: добавлены временные слова
    ]
    
    clarifying_keywords_en = [
        'and why', 'and how', 'and where', 'and when', 'and what', 'and who',
        'why', 'how exactly', 'what exactly', 'when exactly', 'where exactly',
        'tell me', 'more', 'also', 'too', 'then', 'after', 'next',
        'it', 'its', 'their', 'this', 'that', 'those', 'these',
        'tomorrow', 'yesterday', 'today'  # Temporal words
    ]
    
    keywords = clarifying_keywords_ru if detected_language == "russian" else clarifying_keywords_en
    
    user_lower = user_message.lower().strip()
    
    # Проверка 1: Содержит ли вопрос ключевые слова уточнения
    has_clarifying_words = any(keyword in user_lower for keyword in keywords)
    
    # Проверка 2: ОЧЕНЬ короткий вопрос (менее 6 слов) - скорее всего уточнение
    is_very_short = len(user_message.split()) < 6
    
    # Проверка 3: Начинается с вопросительного слова без контекста
    starts_with_question = any(user_lower.startswith(q) for q in ['почему', 'как', 'где', 'когда', 'зачем', 'why', 'how', 'where', 'when'])
    
    # Проверка 4: Начинается с "а " - ВСЕГДА уточнение
    starts_with_a = user_lower.startswith('а ') or user_lower.startswith('and ')
    
    # Проверка 5: Только временные слова (завтра, вчера, сегодня)
    is_temporal_only = user_lower in ['завтра', 'вчера', 'сегодня', 'послезавтра', 'tomorrow', 'yesterday', 'today']
    
    # РАСШИРЕННАЯ ЛОГИКА: считаем уточняющим если:
    # - есть ключевые слова ИЛИ
    # - очень короткий вопрос ИЛИ
    # - начинается с "а " ИЛИ
    # - только временное слово
    is_clarifying = has_clarifying_words or is_very_short or starts_with_a or is_temporal_only
    
    if is_clarifying:
        print(f"[CONTEXTUAL_SEARCH] ✅ Обнаружен УТОЧНЯЮЩИЙ вопрос")
        print(f"[CONTEXTUAL_SEARCH]    - Ключевые слова: {has_clarifying_words}")
        print(f"[CONTEXTUAL_SEARCH]    - Очень короткий (<6 слов): {is_very_short}")
        print(f"[CONTEXTUAL_SEARCH]    - Начинается с 'а': {starts_with_a}")
        print(f"[CONTEXTUAL_SEARCH]    - Только временное слово: {is_temporal_only}")
        
        # Извлекаем последний вопрос пользователя для контекста
        context_parts = []
        
        for i in range(len(history) - 1, -1, -1):
            row = history[i]
            role, content = row[0], row[1]
            
            # Берём последний вопрос пользователя (не текущий)
            if role == "user" and content != user_message:
                context_parts.insert(0, content)
                print(f"[CONTEXTUAL_SEARCH]    Найден предыдущий вопрос: {content[:50]}...")
                break
        
        if context_parts:
            # Формируем расширенный запрос
            main_context = context_parts[0]
            
            # УМНАЯ ОБРАБОТКА УТОЧНЯЮЩИХ ВОПРОСОВ
            user_lower = user_message.lower().strip()
            
            # Если вопрос начинается с "а в/а на" - это изменение места
            # Пример: "погода в Питере" + "а в Мытищах" → "погода в Мытищах"
            if detected_language == "russian":
                # Проверяем паттерны изменения места
                location_change_patterns = [
                    ('а в ', 'в '),
                    ('а на ', 'на '),
                    ('а для ', 'для ')
                ]
                
                for pattern, replacement in location_change_patterns:
                    if user_lower.startswith(pattern):
                        # Извлекаем новое место
                        new_location_part = user_message[len(pattern):]
                        
                        # Заменяем старое место на новое в исходном запросе
                        # Ищем паттерны типа "в [город]", "на [место]"
                        import re
                        # Заменяем первое вхождение предлога + место
                        for prep in ['в ', 'на ', 'для ']:
                            pattern_to_replace = prep + r'\S+'
                            if re.search(pattern_to_replace, main_context.lower()):
                                contextual_query = re.sub(
                                    pattern_to_replace,
                                    replacement + new_location_part,
                                    main_context,
                                    count=1,
                                    flags=re.IGNORECASE
                                )
                                print(f"[CONTEXTUAL_SEARCH] 🔄 Заменено место: '{main_context}' → '{contextual_query}'")
                                return contextual_query
                        
                        # Если не нашли паттерн, добавляем новое место в конец основного запроса
                        contextual_query = main_context.replace(main_context.split()[-1], new_location_part)
                        print(f"[CONTEXTUAL_SEARCH] 🔄 Изменено место (fallback): '{contextual_query}'")
                        return contextual_query
            
            else:
                # Для английского
                location_change_patterns = [
                    ('and in ', 'in '),
                    ('and at ', 'at '),
                    ('and for ', 'for ')
                ]
                
                for pattern, replacement in location_change_patterns:
                    if user_lower.startswith(pattern):
                        new_location_part = user_message[len(pattern):]
                        
                        import re
                        for prep in ['in ', 'at ', 'for ']:
                            pattern_to_replace = prep + r'\S+'
                            if re.search(pattern_to_replace, main_context.lower()):
                                contextual_query = re.sub(
                                    pattern_to_replace,
                                    replacement + new_location_part,
                                    main_context,
                                    count=1,
                                    flags=re.IGNORECASE
                                )
                                print(f"[CONTEXTUAL_SEARCH] 🔄 Replaced location: '{main_context}' → '{contextual_query}'")
                                return contextual_query
                        
                        contextual_query = main_context.replace(main_context.split()[-1], new_location_part)
                        print(f"[CONTEXTUAL_SEARCH] 🔄 Changed location (fallback): '{contextual_query}'")
                        return contextual_query
            
            # Стандартное поведение для других типов уточнений
            # Комбинируем: "основная тема" + "уточняющий вопрос"
            contextual_query = f"{main_context} {user_message}"
            
            print(f"[CONTEXTUAL_SEARCH] ✅ Расширенный запрос: {contextual_query[:100]}...")
            return contextual_query
        else:
            print(f"[CONTEXTUAL_SEARCH] ⚠️  Не найден предыдущий контекст, используем исходный запрос")
            return user_message
    else:
        print(f"[CONTEXTUAL_SEARCH] ℹ️  Самостоятельный вопрос, контекст не требуется")
        return user_message

# Озвучка полностью удалена



def init_db():
    """Инициализирует основную БД. При ошибке — чинит и пересоздаёт."""
    try:
        check_database_health(DB_FILE, required_tables=["messages"], auto_fix=True)
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            content TEXT,
            created_at TEXT)
        """)
        conn.commit()
        conn.close()
        print("[DB] ✅ chat_memory.db готова")
    except Exception as e:
        log_error("INIT_DB", e)
        # Последний шанс — создать пустую БД
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.close()
        except Exception:
            pass

def save_message(role: str, content: str):
    conn = safe_db_connect(DB_FILE)
    if conn is None:
        print("[DB] ⚠️ save_message: нет соединения с БД")
        return
    try:
        conn.execute(
            "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, datetime.utcnow().isoformat())
        )
        conn.commit()
    except Exception as e:
        log_error("SAVE_MSG", e)
    finally:
        conn.close()

def load_history(limit=MAX_HISTORY_LOAD):
    conn = safe_db_connect(DB_FILE)
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = cur.fetchall()
        return list(reversed(rows))
    except Exception as e:
        log_error("LOAD_HISTORY", e)
        return []
    finally:
        conn.close()

def clear_messages():
    conn = safe_db_connect(DB_FILE)
    if conn is None:
        return
    try:
        conn.execute("DELETE FROM messages")
        conn.commit()
    except Exception as e:
        log_error("CLEAR_MSG", e)
    finally:
        conn.close()

# -------------------------
# Model-call helpers
# -------------------------
# call_ollama_vision перенесена в vision_handler.py

# call_ollama_chat и warm_up_model перенесены в llama_handler.py
# Они импортируются выше через 'from llama_handler import ...'

def get_memory_manager(model_key: str):
    """
    Возвращает нужный менеджер памяти в зависимости от модели.
    DeepSeek  → DeepSeekMemoryManager  (deepseek_memory.db)
    Mistral   → MistralMemoryManager   (mistral_memory.db)
    LLaMA и все остальные → ContextMemoryManager (context_memory.db)
    """
    if model_key == "deepseek" and _DS_MEMORY is not None:
        # Возвращаем СИНГЛТОН — чтобы _current_chat_id сохранялся между вызовами
        return _DS_MEMORY
    if model_key == "mistral" and MistralMemoryManager is not None:
        return MistralMemoryManager()
    return ContextMemoryManager()


def get_ai_response(user_message: str, current_language: str, deep_thinking: bool, use_search: bool, should_forget: bool = False, chat_manager=None, chat_id=None, file_paths: list = None, ai_mode: str = AI_MODE_FAST, model_key: str = None):
    """Получить ответ от AI (с жёстким закреплением языка)"""
    # Фиксируем модель ОДИН РАЗ — используем переданный ключ или читаем глобал
    # Это предотвращает любую гонку потоков с llama_handler.CURRENT_AI_MODEL_KEY
    _mk = model_key if model_key is not None else llama_handler.CURRENT_AI_MODEL_KEY
    print(f"\n[GET_AI_RESPONSE] ========== НАЧАЛО ==========")
    print(f"[GET_AI_RESPONSE] Сообщение пользователя: {user_message}")
    print(f"[GET_AI_RESPONSE] Текущий язык интерфейса: {current_language}")
    print(f"[GET_AI_RESPONSE] Глубокое мышление: {deep_thinking}")
    print(f"[GET_AI_RESPONSE] Использовать поиск: {use_search}")
    print(f"[GET_AI_RESPONSE] Забыть историю: {should_forget}")
    print(f"[GET_AI_RESPONSE] Файлов прикреплено: {len(file_paths) if file_paths else 0}")

    # НОРМАЛИЗАЦИЯ МАТЕМАТИЧЕСКИХ СИМВОЛОВ
    # Заменяем специальные символы на стандартные ASCII
    user_message = user_message.replace('×', '*')  # Умножение
    user_message = user_message.replace('÷', '/')  # Деление
    user_message = user_message.replace('−', '-')  # Минус (длинное тире)
    user_message = user_message.replace('±', '+/-')  # Плюс-минус
    user_message = user_message.replace('–', '-')  # Среднее тире
    user_message = user_message.replace('—', '-')  # Длинное тире
    print(f"[GET_AI_RESPONSE] Нормализованное сообщение: {user_message}")

    # ═══════════════════════════════════════════════════════════
    # ОБРАБОТКА КОМАНД ПАМЯТИ
    # ═══════════════════════════════════════════════════════════
    user_lower = user_message.lower().strip()
    
    # Команда "ЗАПОМНИ"
    if chat_id and (user_lower.startswith("запомни") or user_lower.startswith("remember")):
        try:
            context_mgr = get_memory_manager(_mk)
            # Извлекаем текст после команды
            if user_lower.startswith("запомни"):
                memory_text = user_message[7:].strip()  # После "запомни"
                if memory_text.startswith(":"):
                    memory_text = memory_text[1:].strip()
            else:
                memory_text = user_message[8:].strip()  # После "remember"
                if memory_text.startswith(":"):
                    memory_text = memory_text[1:].strip()
            
            if memory_text:
                context_mgr.save_context_memory(chat_id, "user_memory", memory_text)
                print(f"[MEMORY] ✓ Сохранено: {memory_text[:50]}...")
                return "✓ Запомнил!"
        except Exception as e:
            print(f"[MEMORY] ✗ Ошибка сохранения: {e}")

    # ПРОВЕРЯЕМ РОЛЕВУЮ КОМАНДУ
    role_info = detect_role_command(user_message)
    role_instruction = ""
    if role_info["is_role_command"]:
        print(f"[GET_AI_RESPONSE] 🎭 Обнаружена РОЛЕВАЯ КОМАНДА: {role_info['role']}")
        role_instruction = role_info["instruction"]
    
    # ОПРЕДЕЛЯЕМ РЕАЛЬНЫЙ ЯЗЫК ВОПРОСА
    detected_language = detect_message_language(user_message)
    print(f"[GET_AI_RESPONSE] Определённый язык вопроса: {detected_language}")

    # ═══════════════════════════════════════════════════════════
    # DEEPSEEK: BYPASS ПРОСТОЙ АРИФМЕТИКИ
    # Для "25 * 25", "100+200" и т.п. Python считает сам.
    # DeepSeek не вызывается — он генерирует мусор на таких запросах.
    # ═══════════════════════════════════════════════════════════
    if _mk == "deepseek":
        _is_arith, _arith_expr = is_simple_arithmetic(user_message)
        if _is_arith and _arith_expr:
            _arith_result = compute_simple_arithmetic(_arith_expr, detected_language)
            if _arith_result:
                print(f"[GET_AI_RESPONSE] [DeepSeek] Простая арифметика — вычислено Python: {_arith_result}")
                return _arith_result, []

    # ОПРЕДЕЛЯЕМ, ЯВЛЯЕТСЯ ЛИ ЗАПРОС МАТЕМАТИЧЕСКОЙ ЗАДАЧЕЙ
    is_math_problem = detect_math_problem(user_message)
    if is_math_problem:
        print(f"[GET_AI_RESPONSE] 🔬 Обнаружена МАТЕМАТИЧЕСКАЯ ЗАДАЧА - применяю олимпиадный режим")

    # Выбираем режим системного промпта на основе ai_mode
    if ai_mode == AI_MODE_FAST:
        mode = "short"
    elif ai_mode == AI_MODE_THINKING:
        mode = "deep"
    elif ai_mode == AI_MODE_PRO:
        mode = "pro"
    else:
        # Fallback на старую логику если ai_mode не распознан
        mode = "deep" if deep_thinking else "short"
    
    print(f"[GET_AI_RESPONSE] Выбран системный промпт: mode='{mode}', ai_mode='{ai_mode}'")
    # Выбираем промпт в зависимости от текущей модели
    if _mk == "deepseek":
        base_system = get_deepseek_system_prompt(detected_language, mode)
        print(f"[GET_AI_RESPONSE] Используется промпт DeepSeek")
    elif _mk == "mistral":
        base_system = get_mistral_system_prompt(detected_language, mode)
        print(f"[GET_AI_RESPONSE] Используется промпт Mistral Nemo")
        # Если пользователь пытается исправить ИИ — добавляем жёсткое предупреждение
        if detect_user_correction(user_message):
            _warn = (
                "\n\n🔴 ВНИМАНИЕ: ПОЛЬЗОВАТЕЛЬ СЧИТАЕТ ЧТО ТЫ ДОПУСТИЛ ОШИБКУ.\n"
                "1. НЕ СОГЛАШАЙСЯ АВТОМАТИЧЕСКИ.\n"
                "2. Пересчитай с нуля самостоятельно, покажи все шаги.\n"
                "3. Если пользователь прав — признай и исправься.\n"
                "4. Если ты прав — вежливо объясни с доказательством.\n"
                "ЗАПРЕЩЕНО писать 'Вы правы' без собственной проверки."
            )
            base_system = base_system + _warn
            print(f"[GET_AI_RESPONSE] ⚠️ Обнаружена попытка исправления — добавлено предупреждение")
    else:
        base_system = SYSTEM_PROMPTS.get(detected_language, SYSTEM_PROMPTS["russian"])[mode]

    # ══════════════════════════════════════════════════════════
    # ИНЖЕКЦИЯ ТЕКУЩЕЙ ДАТЫ И ВРЕМЕНИ — напрямую из Python
    # Это 100% надёжно — модель не может "забыть" или проигнорировать
    # ══════════════════════════════════════════════════════════
    _now = datetime.now()
    _weekdays_ru = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
    _months_ru   = ["января","февраля","марта","апреля","мая","июня",
                    "июля","августа","сентября","октября","ноября","декабря"]
    _date_ru = f"{_now.day} {_months_ru[_now.month-1]} {_now.year} г., {_weekdays_ru[_now.weekday()]}"
    _time_ru = _now.strftime("%H:%M")
    _date_en = _now.strftime("%B %d, %Y, %A")
    _time_en = _now.strftime("%H:%M")
    if detected_language == "russian":
        _datetime_inject = (
            f"\n\n⚡ СИСТЕМНЫЙ ФАКТ (абсолютно точно, из системных часов компьютера):\n"
            f"• Сегодня: {_date_ru}\n"
            f"• Время сейчас: {_time_ru}\n"
            f"ОБЯЗАТЕЛЬНО используй эти данные при любых вопросах о дате, времени, дне недели.\n"
            f"Твои обучающие данные о датах УСТАРЕЛИ — доверяй только этому системному факту."
        )
    else:
        _datetime_inject = (
            f"\n\n⚡ SYSTEM FACT (exact, from computer system clock):\n"
            f"• Today: {_date_en}\n"
            f"• Current time: {_time_en}\n"
            f"ALWAYS use this when answering questions about date, time, or day of week.\n"
            f"Your training data about dates is OUTDATED — trust only this system fact."
        )
    base_system = base_system + _datetime_inject
    print(f"[GET_AI_RESPONSE] 📅 Инжектирована дата: {_date_ru if detected_language == 'russian' else _date_en}")
    
    # ═══════════════════════════════════════════════════════════
    # ЗАГРУЗКА СОХРАНЁННОЙ ПАМЯТИ
    # DeepSeek читает из deepseek_memory.db, LLaMA — из context_memory.db
    # ═══════════════════════════════════════════════════════════
    memory_context = ""
    if chat_id:
        try:
            context_mgr = get_memory_manager(_mk)
            saved_memories = context_mgr.get_context_memory(chat_id, limit=20)
            
            if saved_memories:
                # Разделяем по типам
                user_memories = [r[1] for r in saved_memories if r[0] == "user_memory"]
                file_analyses = [r[1] for r in saved_memories if r[0] == "file_analysis"]
                
                # Пользовательская память
                if user_memories:
                    if detected_language == "russian":
                        memory_context = "\n\n📌 ВАЖНАЯ ИНФОРМАЦИЯ (пользователь просил запомнить):\n"
                        for idx, mem in enumerate(user_memories, 1):
                            memory_context += f"{idx}. {mem}\n"
                        print(f"[MEMORY] ✓ Загружено {len(user_memories)} записей памяти")
                    else:
                        memory_context = "\n\n📌 IMPORTANT INFORMATION (user asked to remember):\n"
                        for idx, mem in enumerate(user_memories, 1):
                            memory_context += f"{idx}. {mem}\n"
                        print(f"[MEMORY] ✓ Loaded {len(user_memories)} memory records")
                
                # КРИТИЧНО: Добавляем контекст файлов из памяти
                # НО только если в ТЕКУЩЕМ запросе нет своих файлов
                if file_analyses and not (file_paths and len(file_paths) > 0):
                    # Берём последний анализ файлов (самый свежий)
                    latest_file_context = file_analyses[-1]
                    if detected_language == "russian":
                        memory_context += f"\n\n📎 КОНТЕКСТ ИЗ ПРИКРЕПЛЁННЫХ ФАЙЛОВ:\n{latest_file_context}\n"
                        memory_context += "\n(Используй этот контекст только если пользователь спрашивает о файлах. Не упоминай файлы если вопрос не связан с ними.)\n"
                        print(f"[MEMORY] ✓ Загружен контекст файлов ({len(latest_file_context)} символов)")
                    else:
                        memory_context += f"\n\n📎 CONTEXT FROM ATTACHED FILES:\n{latest_file_context}\n"
                        memory_context += "\n(Use this context only if the user asks about files. Don't mention files if the question is unrelated.)\n"
                        print(f"[MEMORY] ✓ Loaded file context ({len(latest_file_context)} chars)")
        except Exception as e:
            print(f"[MEMORY] ✗ Ошибка загрузки памяти: {e}")
    
    # Добавляем математический промпт если это математическая задача
    math_prompt = ""
    if is_math_problem:
        # Выбираем математический промпт в зависимости от модели и режима AI
        if _mk == "deepseek":
            _ds_mode = {"fast": "short", "thinking": "deep", "pro": "pro"}.get(
                ai_mode.lower().replace("быстрый","short").replace("думающий","deep").replace("про","pro"), "short"
            )
            if ai_mode == AI_MODE_FAST:
                _ds_mode = "short"
            elif ai_mode == AI_MODE_THINKING:
                _ds_mode = "deep"
            elif ai_mode == AI_MODE_PRO:
                _ds_mode = "pro"
            math_prompt = get_deepseek_math_prompt(_ds_mode)
            print(f"[GET_AI_RESPONSE] 🔬 DeepSeek математика - режим: {_ds_mode}")
        else:
            if ai_mode == AI_MODE_FAST:
                math_prompt = MATH_PROMPTS["fast"]
                print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: БЫСТРЫЙ")
            elif ai_mode == AI_MODE_THINKING:
                math_prompt = MATH_PROMPTS["thinking"]
                print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: ДУМАЮЩИЙ")
            elif ai_mode == AI_MODE_PRO:
                math_prompt = MATH_PROMPTS["pro"]
                print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: ПРО (олимпиадный)")
            else:
                math_prompt = MATH_PROMPTS["thinking"]
                print(f"[GET_AI_RESPONSE] 🔬 Математика - режим: ДУМАЮЩИЙ (по умолчанию)")
        
        print(f"[GET_AI_RESPONSE] ⚠️ Интернет ЗАПРЕЩЁН для математических задач")
        
        # КРИТИЧНО: Для математических задач ЗАПРЕЩАЕМ интернет
        use_search = False
    
    # ══════════════════════════════════════════════════════════
    # БЛОК ПОНИМАНИЯ КОНТЕКСТА ДИАЛОГА
    # ══════════════════════════════════════════════════════════
    context_understanding_ru = """


═══════════════════════════════════════════════════════════
🧠 ПОНИМАНИЕ КОНТЕКСТА ДИАЛОГА — КРИТИЧЕСКИ ВАЖНО
═══════════════════════════════════════════════════════════

Ты ВСЕГДА читаешь всю историю переписки перед ответом. Это значит:

1. ССЫЛКИ НА ПРОШЛОЕ ("в неё", "в него", "это", "то самое", "оно"):
   • "давай сыграем в неё" → посмотри что обсуждалось выше и пойми что "в неё" = та игра/активность
   • "сделай то же самое" → повтори последнее действие из истории
   • "продолжай" → продолжи то что делал раньше
   • "ещё раз" → повтори предыдущий ответ или действие
   ❌ НЕЛЬЗЯ: делать вид что не понимаешь о чём речь и переспрашивать
   ✅ НУЖНО: найти референс в истории и выполнить просьбу

2. ПРОСЬБА НАЧАТЬ АКТИВНОСТЬ ("давай сыграем", "поиграем", "начнём", "устроим"):
   • Немедленно НАЧНИ эту активность — не объясняй что готов, не описывай правила снова
   • Если это игра — сделай первый ход сам или попроси пользователя начать
   • ❌ НЕЛЬЗЯ: "Я готов! Пожалуйста задавайте вопросы..." — это игнорирование просьбы
   • ✅ НУЖНО: сразу начать играть, назвать первое слово/ход/вопрос

3. УТОЧНЕНИЯ И УСЛОВИЯ ("только по России", "только на букву А", "без повторов"):
   • Запомни условие и соблюдай его во всех последующих ответах
   • ❌ НЕЛЬЗЯ: игнорировать условие или забыть о нём через 1-2 хода
   • ✅ НУЖНО: каждый ответ проверять соответствие условию

4. СМЕНА ТЕМЫ:
   • Если пользователь явно меняет тему — переключайся
   • Если нет — оставайся в контексте текущей активности

ПРИМЕРЫ ПРАВИЛЬНОГО ПОВЕДЕНИЯ:
• Пользователь спросил про игру "Города" → ИИ объяснил
• Пользователь: "давай сыграем, только по России"
• ✅ ИИ: "Отлично! Начинаю: Москва. Ваш ход — называй город на букву 'А'!"
• ❌ ИИ: "Я готов помочь с вопросами о России!" (это провал — он не начал игру)
═══════════════════════════════════════════════════════════"""

    context_understanding_en = """


═══════════════════════════════════════════════════════════
🧠 CONVERSATION CONTEXT UNDERSTANDING — CRITICAL
═══════════════════════════════════════════════════════════

You ALWAYS read the full chat history before responding:

1. REFERENCES TO PAST ("it", "that", "the same", "do it again"):
   • Find the reference in history and act on it immediately
   • ❌ NEVER: pretend you don't understand or ask what they mean
   • ✅ ALWAYS: look back in history and fulfill the request

2. REQUESTS TO START AN ACTIVITY ("let's play", "let's start", "begin"):
   • IMMEDIATELY start the activity — don't just say you're ready
   • ❌ NEVER: "I'm ready! Please ask me questions..." — this ignores the request
   • ✅ ALWAYS: make the first move, say the first word, start the game

3. CONDITIONS AND RULES ("only Russia", "no repeats", "only letter A"):
   • Remember and follow the condition in ALL subsequent responses
═══════════════════════════════════════════════════════════"""

    if detected_language == "russian":
        system_prompt = base_system + memory_context + math_prompt + role_instruction + context_understanding_ru + """

КРИТИЧЕСКИ ВАЖНО - ЯЗЫК ОТВЕТА:
• Отвечай СТРОГО ТОЛЬКО на русском языке
• НЕЛЬЗЯ использовать слова на любом иностранном языке: английском, испанском, итальянском, французском и т.д.
• ЗАПРЕЩЕНО: "turno", "your turn", "turn", "move", "next", "please", "try", "sorry" и любые другие иностранные слова
• Вместо иностранных слов используй ТОЛЬКО русские: "ваш ход", "попробуйте", "извините", "далее" и т.д.
• Русские эквиваленты: however→однако, therefore→поэтому, important→важный, turn→ход, your→ваш, try→попробуйте"""
    else:
        system_prompt = base_system + memory_context + math_prompt + role_instruction + context_understanding_en

    final_user_message = user_message
    all_files_context = []  # Инициализируем заранее — используется позже вне блока if file_paths
    
    # Обрабатываем прикреплённые файлы
    if file_paths and len(file_paths) > 0:
        print(f"[GET_AI_RESPONSE] Обработка файлов: {len(file_paths)}")
        
        for file_path in file_paths:
            # УЛУЧШЕНИЕ: Нормализуем путь к файлу
            file_path = os.path.normpath(os.path.abspath(file_path))
            print(f"[GET_AI_RESPONSE] Обработка файла: {file_path}")
            print(f"[GET_AI_RESPONSE] ════════════════════════════════════════")
            
            try:
                file_ext = os.path.splitext(file_path)[1].lower()
                file_name = os.path.basename(file_path)
                
                # ПРОВЕРКА: убеждаемся что файл существует
                if not os.path.exists(file_path):
                    print(f"[GET_AI_RESPONSE] ⚠️ ФАЙЛ НЕ НАЙДЕН: {file_path}")
                    
                    # Возвращаем понятную ошибку пользователю
                    if detected_language == "russian":
                        error_msg = f"""🔴 Файл '{file_name}' не найден

Путь: {file_path}

Возможные причины:
• Файл был перемещён или удалён
• Неправильный путь к файлу
• Проблема с правами доступа

Попробуйте:
1. Прикрепите файл заново
2. Убедитесь что файл существует на диске
3. Проверьте права доступа к файлу"""
                    else:
                        error_msg = f"""🔴 File '{file_name}' not found

Path: {file_path}

Possible reasons:
• File was moved or deleted
• Incorrect file path
• Access permission issue

Try:
1. Attach the file again
2. Make sure the file exists on disk
3. Check file access permissions"""
                    
                    return error_msg
                
                # Проверяем тип файла
                if is_image_file(file_path):
                    # ═══════════════════════════════════════════════════════
                    # ИЗОБРАЖЕНИЕ — делегируем в vision_handler.py
                    # ═══════════════════════════════════════════════════════
                    result = process_image_file(
                        file_path=file_path,
                        file_name=file_name,
                        user_message=user_message,
                        ai_mode=ai_mode,
                        language=detected_language,
                    )
                    if result["success"]:
                        all_files_context.append(f"[Изображение: {file_name}]\n{result['content']}")
                    else:
                        return result["content"]

                else:
                    # ═══════════════════════════════════════════════════════
                    # ТЕКСТОВЫЙ ФАЙЛ - Читаем и обрабатываем обычной моделью
                    # ═══════════════════════════════════════════════════════
                    print(f"[GET_AI_RESPONSE] 📄 ТИП: ТЕКСТОВЫЙ ФАЙЛ")
                    print(f"[GET_AI_RESPONSE] 🤖 МОДЕЛЬ: {OLLAMA_MODEL} (обычная модель)")
                    print(f"[GET_AI_RESPONSE] 📖 Чтение файла...")
                    
                    try:
                        # Пробуем разные кодировки
                        encodings = ['utf-8', 'cp1251', 'latin-1']
                        file_content = None
                        used_encoding = None
                        
                        for encoding in encodings:
                            try:
                                with open(file_path, 'r', encoding=encoding) as f:
                                    file_content = f.read()[:10000]  # Ограничиваем 10000 символов
                                used_encoding = encoding
                                break
                            except UnicodeDecodeError:
                                continue
                        
                        if file_content:
                            if detected_language == "russian":
                                all_files_context.append(f"""[Файл: {file_name}]
СОДЕРЖИМОЕ:
{file_content}""")
                            else:
                                all_files_context.append(f"""[File: {file_name}]
CONTENT:
{file_content}""")
                            print(f"[GET_AI_RESPONSE] ✅ Файл прочитан ({used_encoding}): {file_name}")
                        else:
                            raise UnicodeDecodeError("all", b"", 0, 0, "Could not decode with any encoding")
                            
                    except Exception as e:
                        # Не удалось прочитать как текст
                        print(f"[GET_AI_RESPONSE] ❌ Не удалось прочитать файл: {file_name} ({e})")
                        
                        # Показываем понятное сообщение
                        if detected_language == "russian":
                            error_msg = f"""⚠️ Файл '{file_name}' не может быть прочитан

Возможные причины:
• Это бинарный файл (exe, pdf, docx и т.д.)
• Неподдерживаемая кодировка

Поддерживаемые текстовые файлы: .txt, .py, .js, .html, .css, .md и др.
Для изображений используйте форматы: .png, .jpg, .jpeg, .gif"""
                        else:
                            error_msg = f"""⚠️ File '{file_name}' cannot be read

Possible reasons:
• This is a binary file (exe, pdf, docx, etc.)
• Unsupported encoding

Supported text files: .txt, .py, .js, .html, .css, .md, etc.
For images use formats: .png, .jpg, .jpeg, .gif"""
                        
                        return error_msg
                        
            except Exception as e:
                print(f"[GET_AI_RESPONSE] Ошибка обработки файла {file_name}: {e}")
                import traceback
                traceback.print_exc()
        
        # Объединяем контекст всех файлов
        if all_files_context:
            # Формируем инструкцию в зависимости от режима
            if ai_mode == AI_MODE_FAST:
                if detected_language == "russian":
                    file_instruction = "Кратко ответь на вопрос используя информацию из файлов."
                else:
                    file_instruction = "Answer briefly using information from the files."
            elif ai_mode == AI_MODE_THINKING:
                if detected_language == "russian":
                    file_instruction = "Проанализируй содержимое файлов. Дай развернутый ответ с примерами и пояснениями."
                else:
                    file_instruction = "Analyze the file contents. Provide a detailed answer with examples and explanations."
            else:  # PRO
                if detected_language == "russian":
                    file_instruction = """Максимально глубокий анализ файлов:
1. Обзор всех файлов
2. Ключевые моменты из каждого файла
3. Связи между файлами (если применимо)
4. Детальный ответ на вопрос пользователя с обоснованием"""
                else:
                    file_instruction = """Maximum deep file analysis:
1. Overview of all files
2. Key points from each file
3. Connections between files (if applicable)
4. Detailed answer to user's question with justification"""
            
            files_context = "\n\n".join(all_files_context)
            
            if detected_language == "russian":
                final_user_message = f"""[Пользователь прикрепил {len(file_paths)} файл(ов)]

{files_context}

ИНСТРУКЦИЯ:
{file_instruction}

Вопрос/сообщение пользователя: {user_message}

ВАЖНО: 
- Если пользователь просто прислал файл без вопроса (например "как тебе фотка?" или просто название файла), ОБЯЗАТЕЛЬНО:
  1. Опиши ЧТО изображено/написано в файле
  2. Дай свою оценку/комментарий
  3. Задай уточняющий вопрос если нужно
- Если есть конкретный вопрос - отвечай на него используя информацию из файла
- Отвечай естественно, как будто видишь файл и обсуждаешь его с другом"""
            else:
                final_user_message = f"""[User attached {len(file_paths)} file(s)]

{files_context}

INSTRUCTION:
{file_instruction}

User's question/message: {user_message}

IMPORTANT:
- If user just sent a file without specific question (e.g. "how's the photo?" or just filename), YOU MUST:
  1. Describe WHAT is shown/written in the file
  2. Give your assessment/comment
  3. Ask clarifying question if needed
- If there's a specific question - answer it using file information
- Respond naturally, as if you're seeing the file and discussing it with a friend"""
            
            print(f"[GET_AI_RESPONSE] Все файлы добавлены в контекст")
            
            # ═══════════════════════════════════════════════════════════
            # СОХРАНЕНИЕ КОНТЕКСТА ФАЙЛОВ В ПАМЯТЬ
            # ═══════════════════════════════════════════════════════════
            # КРИТИЧНО: Сохраняем результаты анализа файлов в историю
            # чтобы AI помнил содержимое файлов в следующих сообщениях
            if chat_id and all_files_context:
                try:
                    context_mgr = get_memory_manager(_mk)
                    files_summary = "\n\n".join(all_files_context)
                    
                    # Сохраняем компактную версию для истории
                    # Ограничиваем длину чтобы не засорять память
                    max_length = 2000  # Максимум 2000 символов
                    if len(files_summary) > max_length:
                        files_summary = files_summary[:max_length] + "...[содержимое обрезано]"
                    
                    context_mgr.save_context_memory(chat_id, "file_analysis", files_summary)
                    print(f"[GET_AI_RESPONSE] ✓ Контекст файлов сохранён в память ({len(files_summary)} символов)")
                except Exception as e:
                    print(f"[GET_AI_RESPONSE] ⚠️ Ошибка сохранения контекста файлов: {e}")
    
    print(f"[GET_AI_RESPONSE] Контекстная память добавлена в системный промпт")

    found_sources = []  # Список (title, url) — заполняется если был поиск

    if use_search:
        print(f"[GET_AI_RESPONSE] ПОИСК АКТИВИРОВАН! Выполняю поиск...")
        if detected_language == "russian":
            region = "ru-ru"
        else:
            region = "us-en"
        num_results = 8 if deep_thinking else 3
        
        # 🔥 КОНТЕКСТНЫЙ ПОИСК: формируем запрос с учётом истории диалога
        contextual_query = build_contextual_search_query(user_message, chat_manager, chat_id, detected_language)
        print(f"[GET_AI_RESPONSE] 🔍 Поисковый запрос: {contextual_query}")
        
        # ── Маршрутизация запросов: версии ПО → специальный пайплайн ──
        # Запросы о версиях, релизах, changelog обрабатываются модульным
        # пайплайном version_search_pipeline (search→filter→extract→validate→answer),
        # который делает несколько поисковых запросов, фильтрует источники
        # по качеству, извлекает и валидирует версии, формирует ответ
        # с явным запретом на галлюцинации.
        _is_version_q = is_version_query(contextual_query)

        if _is_version_q:
            print(f"[GET_AI_RESPONSE] 📦 ОПРЕДЕЛЁН ЗАПРОС О ВЕРСИИ ПО "
                  f"→ Запускаю version_search_pipeline")
            search_results, _page_contents = version_search_pipeline(
                contextual_query,
                region=region,
                language=detected_language,
            )
            # Если пайплайн ничего не вернул — откатываемся к обычному поиску
            if not _page_contents:
                print(f"[GET_AI_RESPONSE] ⚠️ Пайплайн версий пуст, откатываюсь к deep_web_search")
                _is_version_q = False

        if not _is_version_q:
            # УМНЫЙ ПОИСК: все режимы заходят на сайты, отличается только глубина
            if ai_mode in [AI_MODE_THINKING, AI_MODE_PRO]:
                print(f"[GET_AI_RESPONSE] 🧠 Использую ГЛУБОКИЙ веб-поиск (3 сайта)")
                search_results, _page_contents = deep_web_search(
                    contextual_query, num_results=num_results,
                    region=region, language=detected_language, max_pages=3)
            else:
                print(f"[GET_AI_RESPONSE] ⚡ Использую БЫСТРЫЙ веб-поиск (1 сайт)")
                search_results, _page_contents = deep_web_search(
                    contextual_query, num_results=num_results,
                    region=region, language=detected_language, max_pages=1)

            # ── ЗАЩИТА ОТ ГАЛЛЮЦИНАЦИЙ (только для обычного поиска) ──
            _version_guard = validate_versions_before_answer(_page_contents, contextual_query)
            if _version_guard["retry"]:
                print(
                    f"[VERSION_GUARD] 🔄 Источники устаревшие "
                    f"(лучшая версия: «{_version_guard['best_version']}», "
                    f"причина: {_version_guard['reason']}). "
                    f"Повторяю поиск с уточнёнными ключами..."
                )
                import datetime as _dt
                _retry_q = (f"{contextual_query} latest version release "
                            f"{_dt.datetime.now().year}")
                _retry_str, _retry_pages = deep_web_search(
                    _retry_q, num_results=num_results,
                    region=region, language=detected_language, max_pages=3,
                )
                if _retry_pages:
                    search_results = _retry_str
                    _page_contents = _retry_pages
                    print(f"[VERSION_GUARD] ✅ Повторный поиск: {len(_retry_pages)} свежих страниц")
                else:
                    print(f"[VERSION_GUARD] ⚠️ Повторный поиск пустой, оставляем исходные данные")

            if _version_guard["best_version"]:
                print(f"[VERSION_GUARD] 📌 Лучшая версия: «{_version_guard['best_version']}» "
                      f"из {len(_version_guard['all_versions'])} вариантов")
        
        print(f"[GET_AI_RESPONSE] Результаты поиска получены. Длина: {len(search_results)} символов")
        print(f"[GET_AI_RESPONSE] Первые 300 символов результатов: {search_results[:300]}...")

        # ── Извлекаем источники (Заголовок + Ссылка) для кнопки "Источники" ──
        _src_titles = re.findall(r'Заголовок:\s*(.+)', search_results)
        _src_urls   = re.findall(r'Ссылка:\s*(https?://\S+)', search_results)
        found_sources = []
        for i, url in enumerate(_src_urls):
            title = _src_titles[i].strip() if i < len(_src_titles) else url
            found_sources.append((title, url))
        print(f"[GET_AI_RESPONSE] 🔗 Извлечено источников: {len(found_sources)}")

        # СЖИМАЕМ результаты поиска под лимит токенов
        # Примерно 1 токен ≈ 4 символа для русского, ≈ 3 символа для английского
        # Оставляем место для системного промпта (~500 токенов) и ответа
        if deep_thinking:
            # Режим "Думать" - больше токенов на контекст
            max_search_tokens = 2000  # ~8000 символов для русского
        else:
            # Быстрый режим - меньше токенов
            max_search_tokens = 1000  # ~4000 символов для русского
        
        max_search_chars = max_search_tokens * 4 if detected_language == "russian" else max_search_tokens * 3
        print(f"[GET_AI_RESPONSE] Лимит для результатов поиска: {max_search_tokens} токенов ({max_search_chars} символов)")
        
        if len(search_results) > max_search_chars:
            print(f"[GET_AI_RESPONSE] Результаты поиска слишком длинные, сжимаем...")
            search_results = compress_search_results(search_results, max_search_chars)

        # ══════════════════════════════════════════════════════════
        # НОВЫЙ ПАЙПЛАЙН: суммаризация → анализ вопроса → финальная генерация
        # ══════════════════════════════════════════════════════════

        # ШАГ 1: Извлекаем только факты из сырых результатов
        facts = summarize_sources(search_results, user_message, detected_language)

        # ШАГ 1.5: Проверяем релевантность фактов
        # Если суммаризатор вернул "не найдено" — говорим модели использовать свои знания
        no_facts_markers = ["релевантных фактов не найдено", "no relevant facts found", "не найдено", "нет информации"]
        facts_are_irrelevant = any(marker in facts.lower() for marker in no_facts_markers)
        if facts_are_irrelevant:
            print(f"[GET_AI_RESPONSE] ⚠️ Релевантных фактов из поиска не найдено — модель будет использовать собственные знания")
            if detected_language == "russian":
                facts = f"Поиск не дал релевантных результатов по запросу «{user_message}». Ответь на основе своих знаний."
            else:
                facts = f"Search did not return relevant results for «{user_message}». Answer based on your own knowledge."

        # ШАГ 2: Определяем структуру вопроса
        question_parts = detect_question_parts(user_message)

        # ШАГ 3: Строим финальный промпт
        search_context = build_final_answer_prompt(user_message, facts, question_parts, detected_language)
        print(f"[GET_AI_RESPONSE] Контекст поиска добавлен. Длина: {len(search_context)} символов")
        
        # ИСПРАВЛЕНИЕ: Если есть файлы, добавляем их контекст К поисковым результатам
        if all_files_context:
            files_summary = "\n\n".join(all_files_context)
            if detected_language == "russian":
                final_user_message = f"""{search_context}

[ДОПОЛНИТЕЛЬНО: Пользователь прикрепил {len(file_paths)} файл(ов)]

{files_summary}

Учитывай информацию из ОБЕИХ источников: результаты поиска И прикреплённые файлы."""
            else:
                final_user_message = f"""{search_context}

[ADDITIONALLY: User attached {len(file_paths)} file(s)]

{files_summary}

Consider information from BOTH sources: search results AND attached files."""
            print(f"[GET_AI_RESPONSE] ✓ Контекст файлов СОХРАНЁН при поиске")
        else:
            final_user_message = search_context
    else:
        print(f"[GET_AI_RESPONSE] Поиск НЕ активирован")

    # Если запрошено забывание, НЕ загружаем историю
    if should_forget:
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({
            "role": "user",
            "content": final_user_message
        })
        print(f"[GET_AI_RESPONSE] Режим забывания: история не загружается")
    else:
        # Загружаем историю из chat_manager если доступен, иначе из старой БД
        # ВАЖНО: загружаем историю ДАЖЕ при включенном поиске для учета контекста
        # DeepSeek получает только последние 15 сообщений — короткий контекст,
        # чтобы модель не путалась в длинных переписках
        _history_limit = 15 if _mk == "deepseek" else MAX_HISTORY_LOAD
        if chat_manager and chat_id:
            history = chat_manager.get_chat_messages(chat_id, limit=_history_limit)
            print(f"[GET_AI_RESPONSE] Загружено сообщений из чата {chat_id}: {len(history)}")
        else:
            history = load_history(limit=_history_limit)
            print(f"[GET_AI_RESPONSE] Загружено сообщений из истории: {len(history)}")
        
        # ВАЖНО: пропускаем последнее сообщение истории если оно совпадает с текущим
        # запросом — сообщение пользователя сохраняется в БД ДО вызова ИИ,
        # поэтому без этой защиты оно попадает в историю И добавляется ниже ещё раз.
        # DeepSeek видит дубликат и думает что пользователь повторяется.
        history_to_use = list(history)
        if history_to_use and history_to_use[-1][0] == "user" and history_to_use[-1][1] == user_message:
            history_to_use = history_to_use[:-1]

        messages = [{"role": "system", "content": system_prompt}]
        for msg_data in history_to_use:
            role    = msg_data[0]
            content = msg_data[1]

            # Пропускаем системные сообщения
            if role not in ["user", "assistant"]:
                continue
            messages.append({
                "role": "user" if role == "user" else "assistant",
                "content": content
            })
        messages.append({
            "role": "user",
            "content": final_user_message
        })

        if use_search:
            print(f"[GET_AI_RESPONSE] Режим поиска: история загружена для учета контекста диалога")

    print(f"[GET_AI_RESPONSE] Всего сообщений для отправки в AI: {len(messages)}")

    # ═══════════════════════════════════════════════════════════════════
    # АДАПТИВНОЕ ОПРЕДЕЛЕНИЕ ЛИМИТА ТОКЕНОВ
    # ═══════════════════════════════════════════════════════════════════
    # Вместо жестких лимитов используем умную логику, которая:
    # 1. Анализирует длину запроса пользователя
    # 2. Учитывает режим AI
    # 3. Даёт запас для завершения мысли
    # 
    # ЦЕЛЬ: Избежать обрыва ответов на полуслове
    # ═══════════════════════════════════════════════════════════════════
    
    # Анализируем длину запроса пользователя
    user_message_length = len(user_message)
    
    # Базовые лимиты в зависимости от режима AI
    # DeepSeek получает жёсткие ограничения — модель склонна к болтливости
    if _mk == "deepseek":
        if ai_mode == AI_MODE_FAST:
            base_tokens = 300
        elif ai_mode == AI_MODE_THINKING:
            base_tokens = 600
        elif ai_mode == AI_MODE_PRO:
            base_tokens = 1000
        else:
            base_tokens = 400
    elif ai_mode == AI_MODE_FAST:
        base_tokens = 400  # Быстрый режим - короткие ответы, но не слишком
    elif ai_mode == AI_MODE_THINKING:
        base_tokens = 1200  # Думающий режим - средние ответы
    elif ai_mode == AI_MODE_PRO:
        base_tokens = 2500  # Про режим - детальные ответы
    else:
        base_tokens = 800   # По умолчанию
    
    # Коэффициент на основе длины запроса
    if user_message_length < 50:
        length_multiplier = 1.0  # Короткий вопрос
    elif user_message_length < 200:
        length_multiplier = 1.3  # Средний вопрос - больше деталей
    elif user_message_length < 500:
        length_multiplier = 1.6  # Длинный вопрос - ещё больше деталей
    else:
        length_multiplier = 2.0  # Очень длинный вопрос - максимум деталей
    
    # Коэффициент на основе поиска
    if use_search:
        search_multiplier = 1.2  # С поиском нужно больше токенов для синтеза
    else:
        search_multiplier = 1.0
    
    # Итоговый расчёт с запасом
    calculated_tokens = int(base_tokens * length_multiplier * search_multiplier)
    
    # Безопасные границы (минимум и максимум)
    min_tokens = 300   # Минимум чтобы не обрывать
    max_tokens_limit = 4000  # Максимум для производительности
    
    max_tokens = max(min_tokens, min(calculated_tokens, max_tokens_limit))
    
    print(f"[GET_AI_RESPONSE] Адаптивный расчёт токенов:")
    print(f"  - Режим AI: {ai_mode} (база: {base_tokens})")
    print(f"  - Длина запроса: {user_message_length} символов (множитель: {length_multiplier}x)")
    print(f"  - Поиск: {'да' if use_search else 'нет'} (множитель: {search_multiplier}x)")
    print(f"  - Итоговый лимит: {max_tokens} токенов")

    # Увеличиваем timeout для сложных запросов
    if use_search and deep_thinking:
        timeout = 180  # 3 минуты для поиска + глубокое мышление
    elif use_search or deep_thinking:
        timeout = 120  # 2 минуты для поиска ИЛИ глубокое мышление
    else:
        timeout = 60   # 1 минута для обычных запросов

    response_text = ""
    
    if USE_OLLAMA:
        print(f"[GET_AI_RESPONSE] Использую Ollama (LLaMA)...")
        try:
            resp = call_ollama_chat(messages, max_tokens=max_tokens, timeout=timeout, model_key=_mk)
            
            # Проверяем, что ответ не является ошибкой
            if not resp.startswith("[Ollama error]") and not resp.startswith("[Ollama timeout]") and not resp.startswith("[Ollama connection error]"):
                print(f"[GET_AI_RESPONSE] Ollama ответил успешно. Длина ответа: {len(resp)}")
                response_text = resp
            else:
                print(f"[GET_AI_RESPONSE] Ollama вернул ошибку: {resp}")
                response_text = "❌ Ошибка: не удалось получить ответ от локальной модели LLaMA. Проверьте:\n1. Запущена ли Ollama\n2. Загружена ли модель\n3. Достаточно ли памяти"
        except Exception as e:
            print(f"[GET_AI_RESPONSE] Исключение при вызове Ollama: {e}")
            response_text = f"❌ Ошибка подключения к LLaMA: {e}"
    
    # ══════════════════════════════════════════════════════════
    # ШАГ 4 ПАЙПЛАЙНА: Валидация ответа и перегенерация при необходимости
    # ══════════════════════════════════════════════════════════
    if use_search and response_text and not response_text.startswith("❌"):
        facts_for_validation = locals().get("facts", "")
        validation = validate_answer(response_text, user_message, detected_language, facts_for_validation)
        
        if not validation["valid"]:
            print(f"[GET_AI_RESPONSE] 🔄 Ответ не прошёл валидацию, перегенерирую...")
            try:
                regen_prompt = build_final_answer_prompt(
                    user_message, facts_for_validation,
                    detect_question_parts(user_message),
                    detected_language, validation["issues"]
                )
                regen_messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": regen_prompt}
                ]
                regen_resp = call_ollama_chat(regen_messages, max_tokens=max_tokens, timeout=timeout, model_key=_mk)
                if regen_resp and not regen_resp.startswith("[Ollama"):
                    print(f"[GET_AI_RESPONSE] ✓ Перегенерация успешна. Длина: {len(regen_resp)}")
                    response_text = regen_resp
                else:
                    print(f"[GET_AI_RESPONSE] ⚠️ Перегенерация не удалась, оставляю первый ответ")
            except Exception as e:
                print(f"[GET_AI_RESPONSE] ⚠️ Ошибка перегенерации: {e}")

    # КРИТИЧЕСКАЯ ПРОВЕРКА: если вопрос на русском, но ответ содержит много английского - переводим
    if detected_language == "russian":
        # Проверяем, есть ли в ответе много английского
        response_lang = detect_message_language(response_text)
        if response_lang == "english":
            print(f"[GET_AI_RESPONSE] ⚠️⚠️⚠️ КРИТИЧНО! Ответ ПОЛНОСТЬЮ на английском! Переводим...")
            try:
                response_text = translate_to_russian(response_text)
                print(f"[GET_AI_RESPONSE] ✓ Перевод завершён успешно")
            except Exception as e:
                print(f"[GET_AI_RESPONSE] ✗ Ошибка перевода: {e}")
    
    # ═══════════════════════════════════════════════════════════════
    # DEEPSEEK: очистка LaTeX-разметки из ответа
    # DeepSeek иногда генерирует \frac{}{}, \sqrt{}, $...$, что
    # не рендерится и выглядит как мусор. Заменяем на читаемый текст.
    # ═══════════════════════════════════════════════════════════════
    if _mk == "deepseek" and response_text and not response_text.startswith("❌"):
        # ШАГ 1: Проверяем на мусор (scss-блоки, выдуманные формулы и т.п.)
        # Расширено: проверяем мусор даже если is_math_problem=False, но в запросе есть арифметика
        _should_check_garbage = is_math_problem
        if not _should_check_garbage and re.search(r'\d+\s*[\+\-\*\/\%\^]\s*\d+', user_message):
            _should_check_garbage = True
        if _should_check_garbage and is_garbage_math_response(response_text):
            print(f"[GET_AI_RESPONSE] [DeepSeek] ⚠️ Обнаружен мусорный мат. ответ — заменяю!")
            response_text = sanitize_deepseek_math(response_text, user_message, detected_language)
        # ШАГ 2: Очищаем LaTeX из оставшегося ответа
        response_text = clean_deepseek_latex(response_text)
        print(f"[GET_AI_RESPONSE] [DeepSeek] LaTeX-разметка очищена")
    
    # ═══════════════════════════════════════════════════════════════
    # ФИЛЬТРАЦИЯ CJK + АНГЛИЙСКИХ СЛОВ
    # ═══════════════════════════════════════════════════════════════
    # Постобработка ответа Mistral — убираем артефакты токенизатора
    if _mk == "mistral" and response_text and not response_text.startswith("❌"):
        response_text = clean_mistral_response(response_text)
        print(f"[GET_AI_RESPONSE] [Mistral] Постобработка применена")

    # CJK (китайский/японский/корейский) фильтруем ВСЕГДА для deepseek
    if _mk == "deepseek" and response_text:
        import re as _re_cjk_check
        _cjk = _re_cjk_check.compile(
            '[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
            '\u3000-\u303f\u30a0-\u30ff\u3040-\u309f\uac00-\ud7af]+'
        )
        if _cjk.search(response_text):
            response_text = _cjk.sub('', response_text)
            response_text = re.sub(r'  +', ' ', response_text).strip()
            print("[GET_AI_RESPONSE] [DeepSeek] ⚠️ CJK-символы удалены из ответа")
            print(f"[GET_AI_RESPONSE] [DeepSeek] ⚠️ CJK-символы удалены из ответа")
    # Используем расширенный словарь из forbidden_english_words.py
    if detected_language == "russian":
        print(f"[GET_AI_RESPONSE] Фильтрация английских слов...")
        response_text = remove_english_words_from_russian(response_text)
    
    # ИСПРАВЛЕНО: НЕ сохраняем полный контекст поиска, чтобы избежать дублирования
    # Сохраняем только метаданные о том, что поиск был выполнен
    if use_search and chat_id and response_text:
        try:
            context_mgr = get_memory_manager(_mk)
            # Только факт поиска, БЕЗ содержимого ответа
            context_entry = f"[Поиск] {user_message[:80]}"
            context_mgr.save_context_memory(chat_id, "search_meta", context_entry)
            print(f"[GET_AI_RESPONSE] Сохранены метаданные поиска (без дублирования)")
        except Exception as e:
            print(f"[GET_AI_RESPONSE] Ошибка сохранения метаданных: {e}")
    
    print(f"[GET_AI_RESPONSE] ========== КОНЕЦ ==========\n")
    return response_text, found_sources

# -------------------------
# New helper: decide short text
# -------------------------
def is_short_text(text: str) -> bool:
    """
    Возвращает True если текст короткий — критерии:
    - по символам меньше SHORT_TEXT_THRESHOLD, и
    - не более 2 строк
    """
    if not text:
        return True
    s = text.strip()
    lines = s.count("\n") + 1
    return len(s) <= SHORT_TEXT_THRESHOLD and lines <= 2

# -------------------------
# Animated Checkbox
# -------------------------
class AnimatedCheckBox(QtWidgets.QCheckBox):
    """Чекбокс с плавной анимацией масштабирования через размер шрифта"""
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        
        # Флаг блокировки быстрых нажатий
        self.animation_in_progress = False
        
        try:
            # Сохраняем исходный размер шрифта с проверкой
            self.original_font = self.font()
            self.original_font_size = self.original_font.pointSize()
            if self.original_font_size <= 0:
                self.original_font_size = 11  # Дефолт для чекбоксов
            
            # Анимация размера шрифта
            self.font_animation = QtCore.QVariantAnimation()
            self.font_animation.setDuration(180)  # Быстро и плавно
            self.font_animation.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
            self.font_animation.valueChanged.connect(self.update_font_size)
        except Exception as e:
            print(f"[AnimatedCheckBox] Ошибка инициализации: {e}")
            self.original_font_size = 11
    
    def update_font_size(self, size):
        """Обновляет размер шрифта для эффекта масштабирования"""
        try:
            if hasattr(self, 'original_font') and size > 0:
                new_font = QtGui.QFont(self.original_font)
                new_font.setPointSize(int(size))
                self.setFont(new_font)
        except Exception as e:
            print(f"[AnimatedCheckBox] Ошибка update_font_size: {e}")
    
    def nextCheckState(self):
        """Переопределяем для добавления анимации"""
        if self.animation_in_progress:
            return
        
        try:
            # Запускаем анимацию
            self.start_animation()
        except Exception as e:
            print(f"[AnimatedCheckBox] Ошибка анимации: {e}")
        
        # Вызываем родительский метод
        super().nextCheckState()
    
    def start_animation(self):
        """Плавная анимация увеличения/уменьшения при клике"""
        try:
            self.animation_in_progress = True
            
            # Останавливаем текущую анимацию
            if hasattr(self, 'font_animation') and self.font_animation.state() == QtCore.QAbstractAnimation.State.Running:
                self.font_animation.stop()
            
            # Вычисляем размеры
            increase_size = self.original_font_size + 2  # Увеличение на 2pt
            
            # Анимация: нормальный → увеличенный → нормальный
            self.font_animation.setStartValue(self.original_font_size)
            self.font_animation.setKeyValueAt(0.5, increase_size)  # Середина - увеличение
            self.font_animation.setEndValue(self.original_font_size)  # Конец - возврат
            self.font_animation.start()
            
            # Разблокируем
            QtCore.QTimer.singleShot(180, lambda: setattr(self, 'animation_in_progress', False))
        except Exception as e:
            print(f"[AnimatedCheckBox] Ошибка start_animation: {e}")
            self.animation_in_progress = False

# -------------------------
# Glass Tooltip (стеклянная подсказка)
# -------------------------
class GlassTooltip(QtWidgets.QLabel):
    """Стеклянная подсказка с автоисчезновением"""
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setWindowFlags(QtCore.Qt.WindowType.ToolTip | QtCore.Qt.WindowType.FramelessWindowHint)
        # Прозрачность работает плохо на Windows
        if not IS_WINDOWS:
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Стиль стеклянной подсказки
        self.setStyleSheet("""
            QLabel {
                background: rgba(255, 255, 255, 0.75);
                border: 1px solid rgba(255, 255, 255, 0.85);
                border-radius: 12px;
                padding: 8px 14px;
                color: #2d3748;
                font-family: Inter;
                font-size: 13px;
                font-weight: 500;
            }
        """)
        
        # Эффект прозрачности для анимации
        self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)
        
        # Анимация появления
        self.fade_in = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(350)  # 350ms - более плавная анимация
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.setEasingCurve(QtCore.QEasingCurve.Type.OutExpo)  # Более естественная кривая
        
        # Анимация исчезновения
        self.fade_out = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out.setDuration(300)  # 300ms - плавное исчезновение
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QtCore.QEasingCurve.Type.InExpo)  # Симметричная кривая для исчезновения
        self.fade_out.finished.connect(self.hide)
    
    def show_at(self, global_pos):
        """Показать подсказку в указанной позиции"""
        self.adjustSize()
        # Позиционируем чуть ниже кнопки
        self.move(global_pos.x() - self.width() // 2, global_pos.y() + 10)
        self.show()
        self.fade_in.start()
        
        # Автоматически скрыть через 2 секунды
        QtCore.QTimer.singleShot(2000, self.hide_animated)
    
    def hide_animated(self):
        """Плавно скрыть подсказку"""
        self.fade_out.start()

# -------------------------
# FadingScrollArea — top-edge gradient overlay
# -------------------------
class _FadingViewport(QtWidgets.QWidget):
    """
    Drop-in replacement for the default QScrollArea viewport.

    paintEvent():
      1. Calls the normal viewport paint (all child message widgets render).
      2. Paints ONE semi-transparent gradient rect on top.
         • Colour: BLACK with varying alpha → creates subtle fade effect
           without "whitening" the content like white overlay did.
         • Alpha ramp: 0 … ~40 (out of 255) over FADE_HEIGHT pixels.
      3. Zero pixmap allocation per frame — QPainter draws directly into
         the device.  Single drawRect call.  Smooth at 60 fps.
      4. WA_TransparentForMouseEvents ensures gradient doesn't block clicks.
    """
    FADE_HEIGHT = 40   # Height of fade gradient in pixels

    def __init__(self, parent=None):
        super().__init__(parent)
        # ✅ Градиент не должен блокировать клики мыши на MessageWidget
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        # ✅ 1. ОБЯЗАТЕЛЬНО: Normal paint — every child widget (messages) draws itself FIRST.
        super().paintEvent(event)

        # 2. Paint the gradient overlay on top.
        #    Only worth painting when there is something to scroll over
        #    (i.e. content is taller than the viewport).
        scroll_area = self.parent()                          # the QScrollArea
        if scroll_area is None:
            return
        sb = scroll_area.verticalScrollBar()
        if sb is None or sb.maximum() == 0:
            # Nothing scrollable → no messages are hidden → skip.
            return

        # ✅ 3. Создаём QPainter ПОСЛЕ super().paintEvent()
        painter = QtGui.QPainter(self)
        
        # ✅ 4. ОБЯЗАТЕЛЬНО: Устанавливаем режим композиции ПЕРЕД рисованием
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)

        # ✅ 5. Используем полупрозрачный ЧЁРНЫЙ градиент вместо белого
        # Чёрный градиент создаёт затемнение (fade to dark), а не осветление (забеливание)
        # ✅ 6. Градиент рисуется только в верхней зоне FADE_HEIGHT, НЕ по всей высоте
        # ✅ ИСПРАВЛЕНО: Уменьшена интенсивность для более мягкого эффекта
        w = self.width()
        h = self.FADE_HEIGHT  # Только верхняя зона

        grad = QtGui.QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0,  QtGui.QColor(0, 0, 0, 25))   # ✅ Чёрный с alpha 25 вверху (мягче)
        grad.setColorAt(0.5,  QtGui.QColor(0, 0, 0, 10))   # ✅ Чёрный с alpha 10 в середине
        grad.setColorAt(1.0,  QtGui.QColor(0, 0, 0, 0))    # ✅ Полностью прозрачный внизу

        painter.setBrush(grad)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, w, h)  # Рисуем только в верхней зоне FADE_HEIGHT
        painter.end()


# -------------------------
# Скруглённый всплывающий попап (для Источников)
# -------------------------
class RoundedPopup(QtWidgets.QFrame):
    """QFrame с настоящими скруглёнными углами через paintEvent"""
    
    def __init__(self, radius=14, bg="#ffffff", border_color="rgba(200,205,225,0.9)", parent=None):
        super().__init__(parent)
        self._radius = radius
        self._bg = bg
        self._border_color = border_color
        self.setWindowFlags(
            QtCore.Qt.WindowType.Popup |
            QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        # Прозрачный фон у самого виджета — рисуем сами
        self.setStyleSheet("background: transparent; border: none;")
    
    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QPainterPath, QPen
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        path = QtGui.QPainterPath()
        path.addRoundedRect(
            QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
            self._radius, self._radius
        )
        
        # Заливка
        painter.setClipPath(path)
        painter.fillPath(path, QtGui.QColor(self._bg))
        
        # Граница
        pen = QtGui.QPen(QtGui.QColor(self._border_color))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()


# -------------------------
# Message widget (с адаптивным размером эмодзи)
# -------------------------
class MessageWidget(QtWidgets.QWidget):
    """Виджет для отображения сообщения"""

    def __init__(self, speaker: str, text: str, add_controls: bool = False,
                 language: str = "russian", main_window=None, parent=None, thinking_time: float = 0, action_history: list = None, attached_files: list = None, sources: list = None, is_acknowledgment: bool = False):
        super().__init__(parent)
        
        # ✅ КРИТИЧНО: Size policy для виджета сообщения
        # Preferred по горизонтали - занимает предпочтительную ширину
        # Minimum по вертикали - НЕ позволяет layout сжимать виджет ниже его содержимого
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,   # Horizontal - предпочтительная ширина
            QtWidgets.QSizePolicy.Policy.Minimum      # Vertical - НЕ сжимается!
        )
        
        self.text = text
        self.language = language
        self.speaker = speaker  # Сохраняем спикера
        self.main_window = main_window  # Ссылка на главное окно
        self.copy_button = None  # Ссылка на кнопку копирования для анимации
        self.thinking_time = thinking_time  # Время обдумывания в секундах
        self.action_history = action_history or []  # История действий
        self.is_acknowledgment = is_acknowledgment  # Быстрый ответ без AI (нет регенерации)
        self.attached_files = list(attached_files) if attached_files else []  # Файлы для восстановления при отмене
        
        # ── История перегенерации ─────────────────────────────────────────
        # Каждая запись: {"text": str, "thinking_time": float, "action_history": list, "sources": list}
        self._regen_history = [{"text": text, "thinking_time": thinking_time, "action_history": action_history or [], "sources": sources or [], "speaker": speaker}]
        self._regen_idx = 0          # текущий индекс
        self._regen_prev_btn = None  # кнопка «‹»
        self._regen_next_btn = None  # кнопка «›»
        self._regen_counter = None   # метка «2/3»
        
        # Создаём эффект прозрачности для анимации
        self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)  # Начинаем с полной прозрачности

        # ═══════════════════════════════════════════════════════════════════════
        # ПОЛУЧАЕМ НАСТРОЙКИ LIQUID GLASS И ТЕМЫ ИЗ ГЛАВНОГО ОКНА
        # ═══════════════════════════════════════════════════════════════════════
        liquid_glass = True  # По умолчанию включено
        theme = "light"  # По умолчанию светлая
        
        if main_window:
            # Пытаемся загрузить сохранённые настройки
            try:
                if os.path.exists("app_settings.json"):
                    with open("app_settings.json", "r", encoding="utf-8") as f:
                        settings = json.load(f)
                        liquid_glass = settings.get("liquid_glass", True)
                        theme = settings.get("theme", "light")
            except Exception as e:
                print(f"[MSG_WIDGET] Не удалось загрузить настройки: {e}")

        # Сохраняем настройки для возможности обновления стилей
        self.current_theme = theme
        self.current_liquid_glass = liquid_glass

        # ═══════════════════════════════════════════════════════════════════════
        # ПРАВИЛЬНАЯ ЛОГИКА: СНАЧАЛА ТЕМА, ПОТОМ СТЕКЛО
        # ═══════════════════════════════════════════════════════════════════════
        # 
        # ЛОГИКА:
        # 1. Определяем базовые цвета по speaker
        # 2. Определяем тему (light/dark)
        # 3. Применяем liquid_glass (glass/matte)
        # 
        # РЕЗУЛЬТАТ:
        # Light + Glass → светлые стеклянные пузыри
        # Light + NoGlass → светлые матовые пузыри
        # Dark + Glass → тёмные стеклянные пузыри (НЕ светлые!)
        # Dark + NoGlass → тёмные матовые пузыри
        # ═══════════════════════════════════════════════════════════════════════
        
        # Цвет и выравнивание пузыря
        if speaker == "Вы":
            color = "#667eea"
            align = QtCore.Qt.AlignmentFlag.AlignRight
        elif speaker == "Система":
            color = "#48bb78"
            align = QtCore.Qt.AlignmentFlag.AlignCenter
        else:  # Ассистент
            color = "#764ba2"
            align = QtCore.Qt.AlignmentFlag.AlignLeft
        
        # Применяем стили на основе темы и liquid_glass
        if theme == "dark":
            # ═══ ТЁМНАЯ ТЕМА ═══
            if liquid_glass:
                # ТЁМНОЕ СТЕКЛО (прозрачное, с blur)
                bubble_bg = "rgba(35, 35, 40, 0.75)"
                bubble_border = "rgba(50, 50, 55, 0.6)"
                text_color = "#f0f0f0"
                btn_bg = "rgba(45, 45, 50, 0.55)"
                btn_bg_hover = "rgba(55, 55, 60, 0.65)"
                btn_border = "rgba(60, 60, 65, 0.4)"
                # Стекло не использует box-shadow
                box_shadow = "none"
            else:
                # ТЁМНЫЙ МАТОВЫЙ (solid, без прозрачности)
                # Добавляем легкую тень для depth
                bubble_bg = "rgb(43, 43, 48)"
                bubble_border = "rgba(60, 60, 65, 0.95)"  # Чуть темнее border
                text_color = "#f0f0f0"
                btn_bg = "rgb(38, 38, 42)"
                btn_bg_hover = "rgb(48, 48, 52)"
                btn_border = "rgba(58, 58, 62, 0.95)"
                # Subtle elevation с тенью
                box_shadow = "0 2px 8px rgba(0, 0, 0, 0.3)"
        else:
            # ═══ СВЕТЛАЯ ТЕМА ═══
            if liquid_glass:
                # СВЕТЛОЕ СТЕКЛО (прозрачное, с blur)
                bubble_bg = "rgba(255, 255, 255, 0.45)"
                bubble_border = "rgba(255, 255, 255, 0.65)"
                text_color = "#1a202c"
                btn_bg = "rgba(255, 255, 255, 0.55)"
                btn_bg_hover = "rgba(255, 255, 255, 0.75)"
                btn_border = "rgba(255, 255, 255, 0.72)"
                # Стекло не использует box-shadow
                box_shadow = "none"
            else:
                # СВЕТЛЫЙ МАТОВЫЙ (solid, без прозрачности)
                # Добавляем легкую тень для depth
                bubble_bg = "rgb(242, 242, 245)"
                bubble_border = "rgba(200, 200, 205, 0.95)"  # Чуть темнее border
                text_color = "#1a1a1a"
                btn_bg = "rgb(235, 235, 240)"
                btn_bg_hover = "rgb(225, 225, 230)"
                btn_border = "rgba(200, 200, 205, 0.95)"
                # Subtle elevation с тенью
                box_shadow = "0 2px 8px rgba(0, 0, 0, 0.15)"
        
        # Сохраняем стили для использования в кнопках и обновлениях
        self.bubble_bg = bubble_bg
        self.bubble_border = bubble_border
        self.box_shadow = box_shadow
        self.btn_bg = btn_bg
        self.btn_bg_hover = btn_bg_hover
        self.btn_border = btn_border
        self.text_color = text_color
        
        # Определяем цвет иконок в зависимости от liquid_glass и темы
        if liquid_glass:
            if theme == "dark":
                self.icon_color = "#a0a0b0"
            else:
                self.icon_color = "#5a6aaa"
            self.hover_border_color = "rgba(102, 126, 234, 0.40)"
            self.pressed_border_color = "rgba(102, 126, 234, 0.55)"
        else:
            if theme == "dark":
                self.icon_color = "#a0a0b0"
            else:
                self.icon_color = "#5a6aaa"
            self.hover_border_color = btn_border
            self.pressed_border_color = btn_border

        # краткость текста
        short = is_short_text(text)

        # Фиксированные размеры кнопок
        btn_size = 36
        emoji_size = 15
        btn_radius = btn_size // 2

        # главный layout
        main_layout = QtWidgets.QHBoxLayout(self)
        # Для симметрии: сообщения пользователя сдвигаем вправо, ИИ влево
        if align == QtCore.Qt.AlignmentFlag.AlignRight:
            # Сообщения пользователя - ближе к правому краю
            main_layout.setContentsMargins(80, 11, 6, 11)
        elif align == QtCore.Qt.AlignmentFlag.AlignLeft:
            # Сообщения ИИ - ближе к левому краю
            main_layout.setContentsMargins(6, 11, 80, 11)
        else:
            # Системные сообщения - по центру сверху с равными отступами
            main_layout.setContentsMargins(80, 11, 80, 11)
        main_layout.setSpacing(6)
        if align == QtCore.Qt.AlignmentFlag.AlignRight:
            main_layout.addStretch()
        elif speaker == "Система":
            # ✅ Для системных сообщений - центрируем пузырь
            main_layout.addStretch()

        # вертикальный столбик: метка времени (если есть) + пузырь + панель кнопок (вне пузыря)
        col_widget = QtWidgets.QWidget()
        # ✅ Minimum по вертикали - НЕ позволяет сжимать содержимое
        col_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        col_layout = QtWidgets.QVBoxLayout(col_widget)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(2)
        
        # Метка времени обдумывания (только для ИИ, если thinking_time > 0)
        if speaker != "Вы" and speaker != "Система" and thinking_time > 0:
            time_label = QtWidgets.QLabel(f"⏱ думал ~{thinking_time:.1f} с")
            time_label.setStyleSheet("""
                QLabel {
                    color: rgba(90, 106, 170, 0.75);
                    font-size: 11px;
                    font-style: italic;
                    padding: 2px 8px;
                    background: transparent;
                }
            """)
            time_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
            col_layout.addWidget(time_label)

        # пузырь сообщения
        message_container = QtWidgets.QWidget()
        message_container.setObjectName("messageContainer")
        message_container.setMaximumWidth(900)
        message_container.setMinimumWidth(200)
        # ✅ Minimum по вертикали - bubble НЕ сжимается ниже размера текста
        message_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        message_container.setStyleSheet(f"""
            #messageContainer {{
                background-color: {self.bubble_bg};
                border: 1.5px solid {self.bubble_border};
                border-radius: 24px;
                padding: {'28px 44px' if speaker == 'Система' else '26px 34px'};
            }}
        """)
        
        # Сохраняем ссылку для обновления стилей
        self.message_container = message_container
        
        container_layout = QtWidgets.QVBoxLayout(message_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)  # Уменьшено с 6 до 4 для компактности пузыря

        # ─── Файловые бейджи (только для сообщений пользователя с прикреплёнными файлами) ───
        # ═══════════════════════════════════════════════════════════════════
        # ОТОБРАЖЕНИЕ ПРИКРЕПЛЕННЫХ ФАЙЛОВ (ВЫШЕ ПУЗЫРЯ, НЕ ВНУТРИ)
        # ═══════════════════════════════════════════════════════════════════
        if speaker == "Вы" and attached_files and len(attached_files) > 0:
            # Создаём контейнер для файлов ОТДЕЛЬНО от пузыря
            files_container = QtWidgets.QWidget()
            
            # Используем FlowLayout для красивого размещения файлов
            # Если файлов много - они автоматически перенесутся на новую строку
            files_layout = QtWidgets.QHBoxLayout(files_container)
            files_layout.setContentsMargins(0, 0, 0, 8)  # Отступ снизу до пузыря
            files_layout.setSpacing(8)
            files_layout.addStretch()  # Выравнивание справа для сообщений пользователя
            
            # Создаём вложенный контейнер для файлов с переносом
            files_wrapper = QtWidgets.QWidget()
            files_grid = QtWidgets.QGridLayout(files_wrapper)
            files_grid.setSpacing(6)
            files_grid.setContentsMargins(0, 0, 0, 0)
            
            # Показываем бейдж для каждого файла (максимум 3 в строке)
            for idx, file_path_or_name in enumerate(attached_files):
                row = idx // 3  # Строка
                col = idx % 3   # Столбец
                
                # Поддерживаем как полные пути так и просто имена файлов
                display_name_full = os.path.basename(file_path_or_name) if os.sep in file_path_or_name or '/' in file_path_or_name else file_path_or_name
                
                if is_image_file(file_path_or_name):
                    file_emoji = "🖼️"
                elif is_text_file(file_path_or_name):
                    file_emoji = "📄"
                else:
                    file_emoji = "📎"
                display_name = display_name_full if len(display_name_full) <= 30 else display_name_full[:27] + "…"
                # ═══════════════════════════════════════════════════════════════
                # КЛИКАБЕЛЬНАЯ КНОПКА вместо обычного Label
                # ═══════════════════════════════════════════════════════════════
                file_badge = QtWidgets.QPushButton(f"{file_emoji} {display_name}")
                file_badge.setFont(_apple_font(11))
                file_badge.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
                file_badge.setStyleSheet(f"""
                    QPushButton {{
                        color: rgba(102, 126, 234, 1.0);
                        background: rgba(102, 126, 234, 0.12);
                        border: 1px solid rgba(102, 126, 234, 0.28);
                        border-radius: 10px;
                        padding: 4px 10px;
                        text-align: left;
                    }}
                    QPushButton:hover {{
                        background: rgba(102, 126, 234, 0.20);
                        border: 1px solid rgba(102, 126, 234, 0.40);
                    }}
                    QPushButton:pressed {{
                        background: rgba(102, 126, 234, 0.28);
                    }}
                """)
                
                # Сохраняем полный путь как атрибут кнопки для открытия
                file_badge.setProperty("file_name", file_path_or_name)
                file_badge.clicked.connect(lambda checked=False, fn=file_path_or_name: self.open_attached_file(fn))
                
                files_grid.addWidget(file_badge, row, col)
            
            files_layout.addWidget(files_wrapper)
            
            # Добавляем контейнер файлов в главный layout (ВЫШЕ пузыря)
            col_layout.addWidget(files_container, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        message_label = QtWidgets.QLabel()
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse |
            QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        # Ограничиваем максимальную ширину текста
        message_label.setMaximumWidth(850)
        # ✅ Minimum по вертикали - текст НЕ сжимается ниже своего размера
        message_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        
        font = _apple_font(18)
        message_label.setFont(font)
        message_label.setStyleSheet(f"""
            QLabel {{
                color: {self.text_color};
                padding: 8px;
                line-height: 1.6;
                word-wrap: break-word;
            }}
        """)
        
        # Сохраняем ссылку для обновления стилей
        self.message_label = message_label
        
        # Применяем форматирование markdown и математических символов
        formatted_text = format_text_with_markdown_and_math(text)
        display_text = f"<b style='color:{color};'>{speaker}:</b><br>{formatted_text}"
        message_label.setText(display_text)
        self._speaker_color = color  # сохраняем для _regen_apply_entry
        message_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        
        # ✅ MessageWidget только обновляет себя, БЕЗ управления родителем
        # Layout автоматически пересчитает размеры после добавления виджета

        # Центрируем текст если его мало
        if short:
            message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        container_layout.addWidget(message_label)


        # Добавляем контейнер с правильным выравниванием
        if align == QtCore.Qt.AlignmentFlag.AlignCenter:
            # Система - строго по центру
            col_layout.addWidget(message_container, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        elif align == QtCore.Qt.AlignmentFlag.AlignLeft:
            # AI - слева
            col_layout.addWidget(message_container, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        else:
            # Пользователь - справа
            col_layout.addWidget(message_container, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        # Решаем сторону для панели кнопок
        if speaker == "Вы":
            controls_side = "right"
        elif speaker == "Система":
            controls_side = "center"  # ✅ Системные сообщения - кнопки по центру
        else:
            controls_side = "left"

        # панель кнопок (вне пузыря)
        controls_widget = QtWidgets.QWidget()
        controls_layout = QtWidgets.QHBoxLayout(controls_widget)
        controls_layout.setSpacing(10)
        bubble_padding = 18

        if controls_side == "left":
            controls_layout.setContentsMargins(bubble_padding, 4, 0, 6)
        elif controls_side == "right":
            controls_layout.setContentsMargins(0, 4, bubble_padding, 6)
        else:
            controls_layout.setContentsMargins(0, 4, 0, 6)

        # Кнопка копирования - ВСЕГДА видна для ИИ и пользователя
        copy_btn = QtWidgets.QPushButton()
        copy_btn.setText("📋")
        copy_btn.setToolTip("Копировать")
        copy_btn.setFixedSize(btn_size, btn_size)
        copy_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        copy_btn.clicked.connect(self.copy_text)
        # ✅ ИСПРАВЛЕНИЕ: Кнопка копирования видна всегда (игнорируем short)
        copy_btn.setVisible(add_controls)
        copy_btn.setObjectName("floatingControl")
        copy_btn.setStyleSheet(f"""
            QPushButton#floatingControl {{
                background: {self.btn_bg};
                color: {self.icon_color};
                border: 1px solid {self.btn_border};
                border-radius: {btn_radius}px;
                font-size: {emoji_size}px;
            }}
            QPushButton#floatingControl:hover {{ 
                background: {self.btn_bg_hover};
                border: 1px solid {self.hover_border_color};
            }}
            QPushButton#floatingControl:pressed {{ 
                background: {self.btn_bg_hover};
                border: 1px solid {self.pressed_border_color};
            }}
        """)
        self.copy_button = copy_btn  # Сохраняем ссылку для анимации
        controls_layout.addWidget(copy_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
        # Кнопка редактирования (только для пользователя)
        if speaker == "Вы":
            edit_btn = QtWidgets.QPushButton()
            edit_btn.setText("✏️")
            edit_btn.setToolTip("Редактировать")
            edit_btn.setFixedSize(btn_size, btn_size)
            edit_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            edit_btn.clicked.connect(self.edit_message)
            # ✅ Кнопка редактирования создаётся, но видимостью управляет add_message_widget
            edit_btn.setVisible(add_controls)
            edit_btn.setObjectName("floatingControl")
            edit_btn.setStyleSheet(f"""
                QPushButton#floatingControl {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {btn_radius}px;
                    font-size: {emoji_size}px;
                }}
                QPushButton#floatingControl:hover {{ 
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton#floatingControl:pressed {{ 
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.pressed_border_color};
                }}
            """)
            controls_layout.addWidget(edit_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
            # Сохраняем ссылку на кнопку редактирования
            self.edit_button = edit_btn
        else:
            self.edit_button = None

        
        # Кнопка перегенерации (только для ассистента, только если НЕ acknowledgment)
        if speaker != "Вы" and speaker != "Система" and add_controls and not self.is_acknowledgment:
            regenerate_btn = QtWidgets.QPushButton()
            regenerate_btn.setText("🔄")
            regenerate_btn.setToolTip("Перегенерировать ответ")
            regenerate_btn.setFixedSize(btn_size, btn_size)
            regenerate_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            regenerate_btn.clicked.connect(self.regenerate_response)
            # ✅ ИСПРАВЛЕНИЕ: Кнопка перегенерации видна всегда (игнорируем short)
            regenerate_btn.setVisible(add_controls)
            regenerate_btn.setObjectName("floatingControl")
            regenerate_btn.setStyleSheet(f"""
                QPushButton#floatingControl {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {btn_radius}px;
                    font-size: {emoji_size}px;
                }}
                QPushButton#floatingControl:hover {{ 
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton#floatingControl:pressed {{ 
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.pressed_border_color};
                }}
            """)
            controls_layout.addWidget(regenerate_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
            
            # ── Кнопки навигации ‹ 1/1 › ─────────────────────────────────────
            # ВАЖНО: НЕ используем objectName("floatingControl") — иначе глобальный
            # стиль перебивает размеры и кнопки выглядят асимметрично.
            _ns = 28  # nav size
            _nr = _ns // 2
            _nav_btn_css = f"""
                QPushButton {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {_nr}px;
                    font-size: 14px;
                    font-weight: 600;
                    min-width: {_ns}px;
                    max-width: {_ns}px;
                    min-height: {_ns}px;
                    max-height: {_ns}px;
                    padding: 0px;
                    margin: 0px;
                }}
                QPushButton:hover {{
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton:pressed {{ background: {self.btn_bg_hover}; }}
                QPushButton:disabled {{
                    opacity: 0.35;
                }}
            """
            _nav_lbl_css = f"""
                QLabel {{
                    color: {self.icon_color};
                    font-size: 11px;
                    font-weight: 600;
                    background: transparent;
                    border: none;
                    min-width: 28px;
                    max-width: 28px;
                    min-height: {_ns}px;
                    max-height: {_ns}px;
                    padding: 0px;
                    margin: 0px;
                }}
            """

            # Группируем ‹ 1/1 › в один QWidget для симметрии
            nav_group = QtWidgets.QWidget()
            nav_group.setVisible(False)  # скрыт пока 1 вариант
            nav_group_layout = QtWidgets.QHBoxLayout(nav_group)
            nav_group_layout.setContentsMargins(0, 0, 0, 0)
            nav_group_layout.setSpacing(2)

            prev_btn = QtWidgets.QPushButton("‹")
            prev_btn.setFixedSize(_ns, _ns)
            prev_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            prev_btn.setStyleSheet(_nav_btn_css)
            prev_btn.setEnabled(False)
            prev_btn.setToolTip("Предыдущий вариант")
            prev_btn.clicked.connect(self._regen_go_prev)

            counter_lbl = QtWidgets.QLabel("1/1")
            counter_lbl.setFixedSize(28, _ns)
            counter_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            counter_lbl.setStyleSheet(_nav_lbl_css)

            next_btn = QtWidgets.QPushButton("›")
            next_btn.setFixedSize(_ns, _ns)
            next_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            next_btn.setStyleSheet(_nav_btn_css)
            next_btn.setEnabled(False)
            next_btn.setToolTip("Следующий вариант")
            next_btn.clicked.connect(self._regen_go_next)

            nav_group_layout.addWidget(prev_btn)
            nav_group_layout.addWidget(counter_lbl)
            nav_group_layout.addWidget(next_btn)

            controls_layout.addWidget(nav_group, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

            self._regen_prev_btn = prev_btn
            self._regen_counter  = counter_lbl
            self._regen_next_btn = next_btn
            self._regen_nav_group = nav_group
            
            # Сохраняем ссылку на кнопку регенерации для управления видимостью
            self.regenerate_button = regenerate_btn
        else:
            self.regenerate_button = None

        controls_widget.setVisible(add_controls)

        # ── Кнопка "Источники" (только для ассистента, только если был поиск) ──
        self._sources_popup = None
        if speaker != "Вы" and speaker != "Система" and add_controls and sources and not self.is_acknowledgment:
            src_btn = QtWidgets.QPushButton("🔗 Источники")
            src_btn.setToolTip("Показать источники")
            src_btn.setFixedHeight(btn_size)
            src_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            src_btn.setObjectName("sourcesBtn")
            src_btn.setStyleSheet(f"""
                QPushButton#sourcesBtn {{
                    background: {self.btn_bg};
                    color: {self.icon_color};
                    border: 1px solid {self.btn_border};
                    border-radius: {btn_radius}px;
                    font-size: 12px;
                    padding: 0px 10px;
                }}
                QPushButton#sourcesBtn:hover {{
                    background: {self.btn_bg_hover};
                    border: 1px solid {self.hover_border_color};
                }}
                QPushButton#sourcesBtn:pressed {{
                    background: {self.btn_bg_hover};
                }}
            """)
            self.sources_button = src_btn  # Сохраняем для обновления темы

            # Сохраняем источники в замыкании
            _sources = list(sources)

            def _toggle_sources(checked, btn=src_btn, srcs=_sources):
                # Безопасная проверка — C++ объект мог быть уже удалён
                if self._sources_popup is not None:
                    try:
                        visible = self._sources_popup.isVisible()
                    except RuntimeError:
                        self._sources_popup = None
                        visible = False
                    if visible:
                        # Плавное закрытие: fade-out + slide-down
                        popup_ref = self._sources_popup
                        self._sources_popup = None

                        _close_eff = QtWidgets.QGraphicsOpacityEffect(popup_ref)
                        popup_ref.setGraphicsEffect(_close_eff)
                        _close_eff.setOpacity(1.0)

                        _close_op = QtCore.QPropertyAnimation(_close_eff, b"opacity")
                        _close_op.setDuration(180)
                        _close_op.setStartValue(1.0)
                        _close_op.setEndValue(0.0)
                        _close_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

                        cur_geo = popup_ref.geometry()
                        _close_geo = QtCore.QPropertyAnimation(popup_ref, b"geometry")
                        _close_geo.setDuration(180)
                        _close_geo.setStartValue(cur_geo)
                        _close_geo.setEndValue(
                            QtCore.QRect(cur_geo.x(), cur_geo.y() + 10,
                                         cur_geo.width(), cur_geo.height())
                        )
                        _close_geo.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

                        def _do_close(p=popup_ref):
                            try:
                                p.close()
                            except Exception:
                                pass

                        _close_op.finished.connect(_do_close)
                        _close_op.start()
                        _close_geo.start()
                        popup_ref._close_anims = [_close_op, _close_geo, _close_eff]
                        return

                is_dark = getattr(self, 'current_theme', 'light') == 'dark'

                # Цвета по теме
                if is_dark:
                    bg = "#1e1e26"; border_c = "rgba(80,80,110,0.8)"
                    hdr_c = "#8888a8"; card_bg = "#26263a"; card_hover = "#30304a"
                    card_border = "rgba(70,70,100,0.6)"; link_c = "#8ab4f8"
                    domain_c = "#6688cc"; div_c = "rgba(80,80,110,0.3)"; text_bg = "#1e1e26"
                else:
                    bg = "#ffffff"; border_c = "rgba(200,205,225,0.9)"
                    hdr_c = "#888899"; card_bg = "#f5f6fc"; card_hover = "#eaedff"
                    card_border = "rgba(210,215,235,0.8)"; link_c = "#1a56db"
                    domain_c = "#5566aa"; div_c = "rgba(205,210,230,0.6)"; text_bg = "#ffffff"

                popup = RoundedPopup(
                    radius=14,
                    bg=bg,
                    border_color=border_c
                )
                popup.setMinimumWidth(320)
                popup.setMaximumWidth(440)

                outer = QtWidgets.QVBoxLayout(popup)
                outer.setContentsMargins(0, 0, 0, 0)
                outer.setSpacing(0)

                # ── Заголовок ──
                hdr_w = QtWidgets.QWidget()
                hdr_w.setStyleSheet("background: transparent;")
                hl = QtWidgets.QHBoxLayout(hdr_w)
                hl.setContentsMargins(14, 12, 14, 10)
                hl.setSpacing(6)
                ico_l = QtWidgets.QLabel("🔗")
                ico_l.setStyleSheet("background: transparent; font-size: 13px;")
                hl.addWidget(ico_l)
                cnt = len(srcs[:8])
                hdr_t = QtWidgets.QLabel(f"Источники · {cnt}")
                hdr_t.setStyleSheet(f"background: transparent; color: {hdr_c}; font-size: 12px; font-weight: 600; letter-spacing: 0.3px;")
                hl.addWidget(hdr_t)
                hl.addStretch()
                outer.addWidget(hdr_w)

                # Разделитель
                sep = QtWidgets.QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {div_c}; margin: 0 12px;")
                outer.addWidget(sep)

                # ── Список карточек ──
                list_w = QtWidgets.QWidget()
                list_w.setStyleSheet("background: transparent;")
                ll = QtWidgets.QVBoxLayout(list_w)
                ll.setContentsMargins(10, 8, 10, 10)
                ll.setSpacing(5)

                import urllib.parse as _up
                for i, src_item in enumerate(srcs[:8]):
                    # Совместимость: tuple или list
                    stitle = src_item[0] if len(src_item) > 0 else ""
                    surl = src_item[1] if len(src_item) > 1 else ""
                    try:
                        domain = _up.urlparse(surl).netloc.replace("www.", "") or surl[:25]
                    except Exception:
                        domain = surl[:25]

                    card = QtWidgets.QFrame()
                    card.setFixedHeight(58)
                    card.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
                    card.setToolTip(surl)
                    card.setStyleSheet(f"""
                        QFrame {{
                            background: {card_bg};
                            border: 1px solid {card_border};
                            border-radius: 9px;
                        }}
                        QFrame:hover {{
                            background: {card_hover};
                            border: 1px solid {link_c};
                        }}
                    """)

                    ci = QtWidgets.QHBoxLayout(card)
                    ci.setContentsMargins(10, 8, 10, 8)
                    ci.setSpacing(10)

                    # Favicon placeholder
                    fav_l = QtWidgets.QLabel("🌐")
                    fav_l.setFixedSize(22, 22)
                    fav_l.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                    fav_l.setStyleSheet("background: transparent; border: none; font-size: 15px;")
                    ci.addWidget(fav_l)

                    # Текст
                    tc = QtWidgets.QVBoxLayout()
                    tc.setSpacing(2)
                    tc.setContentsMargins(0, 0, 0, 0)

                    short_t = (stitle[:50] + "…") if len(stitle) > 50 else stitle
                    t_lbl = QtWidgets.QLabel(short_t)
                    t_lbl.setStyleSheet(f"background: transparent; color: {link_c}; font-size: 12px; font-weight: 600; border: none;")
                    t_lbl.setWordWrap(False)
                    tc.addWidget(t_lbl)

                    d_lbl = QtWidgets.QLabel(domain)
                    d_lbl.setStyleSheet(f"background: transparent; color: {domain_c}; font-size: 10px; border: none;")
                    tc.addWidget(d_lbl)

                    ci.addLayout(tc)
                    ci.addStretch()

                    arr = QtWidgets.QLabel("↗")
                    arr.setStyleSheet(f"background: transparent; color: {domain_c}; font-size: 13px; border: none;")
                    ci.addWidget(arr)

                    # Клик — открыть URL
                    _u = surl
                    def _on_click(_, url=_u):
                        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
                        popup.close()
                    card.mousePressEvent = _on_click
                    ll.addWidget(card)

                    # Асинхронная загрузка favicon
                    _fav_ref = fav_l
                    _fav_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=32"
                    def _fetch_fav(fu=_fav_url, lbl=_fav_ref):
                        try:
                            r = __import__('requests').get(fu, timeout=3)
                            if r.status_code == 200 and len(r.content) > 100:
                                px = QtGui.QPixmap()
                                px.loadFromData(r.content)
                                if not px.isNull():
                                    def _apply(p=px, l=lbl):
                                        try:
                                            l.setPixmap(p.scaled(22, 22,
                                                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                                QtCore.Qt.TransformationMode.SmoothTransformation))
                                            l.setText("")
                                        except RuntimeError:
                                            pass
                                    QtCore.QTimer.singleShot(0, _apply)
                        except Exception:
                            pass
                    __import__('threading').Thread(target=_fetch_fav, daemon=True).start()

                outer.addWidget(list_w)
                popup.adjustSize()

                # Позиционирование над кнопкой (с проверкой границ экрана)
                btn_global = btn.mapToGlobal(QtCore.QPoint(0, 0))
                ph = popup.sizeHint().height()
                pw = popup.sizeHint().width()
                x = btn_global.x()
                y = btn_global.y() - ph - 8
                scr = QtWidgets.QApplication.screenAt(btn_global)
                if scr:
                    sg = scr.geometry()
                    if x + pw > sg.right() - 8:
                        x = sg.right() - pw - 8
                    if x < sg.left() + 8:
                        x = sg.left() + 8
                    if y < sg.top() + 8:
                        y = btn_global.y() + btn.height() + 8

                popup.move(x, y)
                self._sources_popup = popup
                popup.destroyed.connect(lambda: setattr(self, '_sources_popup', None))

                # Плавное появление: fade-in + slide-up
                popup.show()
                popup.raise_()
                _p_eff = QtWidgets.QGraphicsOpacityEffect(popup)
                popup.setGraphicsEffect(_p_eff)
                _p_eff.setOpacity(0.0)
                _p_op = QtCore.QPropertyAnimation(_p_eff, b"opacity")
                _p_op.setDuration(220)
                _p_op.setStartValue(0.0)
                _p_op.setEndValue(1.0)
                _p_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                # slide-up: стартуем на 12px ниже
                _p_start_geo = QtCore.QRect(x, y + 12, popup.width(), popup.height())
                _p_end_geo   = QtCore.QRect(x, y,      popup.width(), popup.height())
                _p_geo = QtCore.QPropertyAnimation(popup, b"geometry")
                _p_geo.setDuration(220)
                _p_geo.setStartValue(_p_start_geo)
                _p_geo.setEndValue(_p_end_geo)
                _p_geo.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                def _src_cleanup(p=popup, e=_p_eff):
                    try: p.setGraphicsEffect(None)
                    except RuntimeError: pass
                _p_op.finished.connect(_src_cleanup)
                _p_op.start()
                _p_geo.start()
                # держим ссылки
                popup._src_anims = [_p_op, _p_geo, _p_eff]

            src_btn.clicked.connect(_toggle_sources)
            # Кнопка «Источники» — в один ряд с copy/regenerate
            controls_layout.addWidget(src_btn)

        # Добавляем панель под пузырём
        if controls_side == "left":
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        elif controls_side == "right":
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        else:
            col_layout.addWidget(controls_widget, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)
        
        # Вставляем в главный layout
        main_layout.addWidget(col_widget)
        if align == QtCore.Qt.AlignmentFlag.AlignLeft:
            main_layout.addStretch()
        elif speaker == "Система":
            # ✅ Для системных сообщений - добавляем stretch ПОСЛЕ для полного центрирования
            main_layout.addStretch()
        
        # ✅ ИДЕАЛЬНАЯ FADE-IN АНИМАЦИЯ: Плавное появление с оптимальными параметрами
        # Простая, надёжная, красивая - без конфликтов с layout
        if not IS_WINDOWS:
            # Создаём fade-in анимацию с идеальными параметрами
            self.fade_in_animation = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
            self.fade_in_animation.setDuration(450)  # 450ms - быстрая и плавная анимация
            self.fade_in_animation.setStartValue(0.0)
            self.fade_in_animation.setEndValue(1.0)
            # OutCubic - создаёт мягкое замедление в конце для естественного появления
            # Сообщение появляется быстро и элегантно
            self.fade_in_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            
            # ✅ НЕ запускаем анимацию автоматически - она будет запущена из add_message_widget
            # после полного обновления layout
        else:
            # На Windows сразу показываем без анимации
            self.opacity_effect.setOpacity(1.0)

    @QtCore.pyqtSlot()
    def _start_appear_animation(self):
        """
        Запускает идеальную fade-in анимацию появления.
        
        Простая, надёжная, красивая анимация с оптимальными параметрами:
        - 450ms длительность для быстрого и плавного появления
        - OutCubic кривая для естественного замедления
        
        После завершения анимации graphicsEffect удаляется чтобы
        избежать искажения цветов.
        
        Вызывается через QMetaObject.invokeMethod для синхронизации с layout.
        """
        if hasattr(self, 'fade_in_animation'):
            # Подключаем очистку эффекта после завершения анимации
            try:
                self.fade_in_animation.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            
            self.fade_in_animation.finished.connect(self._remove_graphics_effect_after_animation)
            self.fade_in_animation.start()
    
    def _remove_graphics_effect_after_animation(self):
        """
        Удаляет graphicsEffect после завершения анимации.
        Это предотвращает искажение цветов сообщений.
        """
        try:
            # Удаляем graphicsEffect чтобы избежать искажения цветов
            self.setGraphicsEffect(None)
            # Убираем ссылки на анимации
            if hasattr(self, 'fade_in_animation'):
                delattr(self, 'fade_in_animation')
            if hasattr(self, 'opacity_effect'):
                delattr(self, 'opacity_effect')
        except Exception as e:
            # Игнорируем ошибки при очистке
            pass
    
    def _cleanup_graphics_effect(self):
        """
        Завершает анимацию появления - удаляет graphicsEffect.
        
        ВАЖНО: Удаляем graphicsEffect чтобы избежать искажения цветов!
        После анимации эффект больше не нужен.
        """
        try:
            # Удаляем graphicsEffect полностью
            self.setGraphicsEffect(None)
            # Очищаем ссылки
            if hasattr(self, 'opacity_effect'):
                delattr(self, 'opacity_effect')
        except RuntimeError:
            # Объект уже удалён - игнорируем
            pass

    def update_message_styles(self, theme: str, liquid_glass: bool):
        """
        Обновляет стили виджета при изменении настроек темы или liquid_glass.
        
        ВАЖНО: НЕ пересоздаёт виджет, только обновляет стили.
        Layout НЕ изменяется.
        
        Параметры:
        - theme: "light" или "dark"
        - liquid_glass: True/False
        """
        # Сохраняем новые настройки
        self.current_theme = theme
        self.current_liquid_glass = liquid_glass
        
        # Пересчитываем стили по той же логике что и в __init__
        if theme == "dark":
            if liquid_glass:
                # ТЁМНОЕ СТЕКЛО
                bubble_bg = "rgba(35, 35, 40, 0.75)"
                bubble_border = "rgba(50, 50, 55, 0.6)"
                text_color = "#f0f0f0"
                btn_bg = "rgba(45, 45, 50, 0.55)"
                btn_bg_hover = "rgba(55, 55, 60, 0.65)"
                btn_border = "rgba(60, 60, 65, 0.4)"
                icon_color = "#a0a0b0"
                hover_border_color = "rgba(102, 126, 234, 0.40)"
                pressed_border_color = "rgba(102, 126, 234, 0.55)"
                box_shadow = "none"  # Стекло без тени
            else:
                # ТЁМНЫЙ МАТОВЫЙ (с чуть темнее border для depth)
                bubble_bg = "rgb(43, 43, 48)"
                bubble_border = "rgba(60, 60, 65, 0.95)"
                text_color = "#f0f0f0"
                btn_bg = "rgb(38, 38, 42)"
                btn_bg_hover = "rgb(48, 48, 52)"
                btn_border = "rgba(58, 58, 62, 0.95)"
                icon_color = "#a0a0b0"
                hover_border_color = btn_border
                pressed_border_color = btn_border
                box_shadow = "0 2px 8px rgba(0, 0, 0, 0.3)"  # Матовый с тенью
        else:
            if liquid_glass:
                # СВЕТЛОЕ СТЕКЛО
                bubble_bg = "rgba(255, 255, 255, 0.45)"
                bubble_border = "rgba(255, 255, 255, 0.65)"
                text_color = "#1a202c"
                btn_bg = "rgba(255, 255, 255, 0.55)"
                btn_bg_hover = "rgba(255, 255, 255, 0.75)"
                btn_border = "rgba(255, 255, 255, 0.72)"
                icon_color = "#5a6aaa"
                hover_border_color = "rgba(102, 126, 234, 0.40)"
                pressed_border_color = "rgba(102, 126, 234, 0.55)"
                box_shadow = "none"  # Стекло без тени
            else:
                # СВЕТЛЫЙ МАТОВЫЙ (с чуть темнее border для depth)
                bubble_bg = "rgb(242, 242, 245)"
                bubble_border = "rgba(200, 200, 205, 0.95)"
                text_color = "#1a1a1a"
                btn_bg = "rgb(235, 235, 240)"
                btn_bg_hover = "rgb(225, 225, 230)"
                btn_border = "rgba(200, 200, 205, 0.95)"
                icon_color = "#5a6aaa"
                hover_border_color = btn_border
                pressed_border_color = btn_border
                box_shadow = "0 2px 8px rgba(0, 0, 0, 0.15)"  # Матовый с тенью
        
        # Сохраняем новые стили
        self.bubble_bg = bubble_bg
        self.bubble_border = bubble_border
        self.box_shadow = box_shadow  # ✅ ИСПРАВЛЕНИЕ: Добавлено сохранение box_shadow
        self.btn_bg = btn_bg
        self.btn_bg_hover = btn_bg_hover
        self.btn_border = btn_border
        self.text_color = text_color
        self.icon_color = icon_color
        self.hover_border_color = hover_border_color
        self.pressed_border_color = pressed_border_color
        
        # Применяем стили к message_container
        if hasattr(self, 'message_container') and self.message_container:
            # ✅ ИСПРАВЛЕНИЕ: Используем тот же стиль что и в __init__
            self.message_container.setStyleSheet(f"""
                #messageContainer {{
                    background-color: {bubble_bg};
                    border: 1.5px solid {bubble_border};
                    border-radius: 24px;
                    padding: 26px 34px;
                }}
            """)
        
        # Применяем стили к message_label
        if hasattr(self, 'message_label') and self.message_label:
            self.message_label.setStyleSheet(f"""
                QLabel {{
                    color: {text_color};
                    padding: 8px;
                    line-height: 1.6;
                    word-wrap: break-word;
                }}
            """)
        
        # Обновляем стили кнопок (если они есть)
        btn_size = 36
        btn_radius = btn_size // 2
        emoji_size = 15
        
        button_style = f"""
            QPushButton#floatingControl {{
                background: {btn_bg};
                color: {icon_color};
                border: 1px solid {btn_border};
                border-radius: {btn_radius}px;
                font-size: {emoji_size}px;
            }}
            QPushButton#floatingControl:hover {{ 
                background: {btn_bg_hover};
                border: 1px solid {hover_border_color};
            }}
            QPushButton#floatingControl:pressed {{ 
                background: {btn_bg_hover};
                border: 1px solid {pressed_border_color};
            }}
        """
        
        # Применяем к кнопке копирования
        if hasattr(self, 'copy_button') and self.copy_button:
            self.copy_button.setStyleSheet(button_style)
        
        # Применяем ко всем floatingControl кнопкам
        for button in self.findChildren(QtWidgets.QPushButton):
            if button.objectName() == "floatingControl":
                button.setStyleSheet(button_style)

        # Отдельно обновляем кнопку источников (у неё другой objectName)
        if hasattr(self, 'sources_button') and self.sources_button:
            try:
                self.sources_button.setStyleSheet(f"""
                    QPushButton#sourcesBtn {{
                        background: {btn_bg};
                        color: {icon_color};
                        border: 1px solid {btn_border};
                        border-radius: {btn_radius}px;
                        font-size: 12px;
                        padding: 0px 10px;
                    }}
                    QPushButton#sourcesBtn:hover {{
                        background: {btn_bg_hover};
                        border: 1px solid {hover_border_color};
                    }}
                    QPushButton#sourcesBtn:pressed {{
                        background: {btn_bg_hover};
                    }}
                """)
            except RuntimeError:
                pass

        print(f"[MSG_UPDATE] Стили обновлены: theme={theme}, liquid_glass={liquid_glass}")


    def copy_text(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.text)
        
        # Простая анимация: меняем текст и цвет
        if self.copy_button:
            original_text = self.copy_button.text()
            original_style = self.copy_button.styleSheet()
            
            # Меняем на галочку с зеленым цветом
            self.copy_button.setText("✓")
            
            # Добавляем зеленый фон для индикации успеха
            success_style = original_style.replace(
                self.btn_bg, 
                "rgba(72, 187, 120, 0.3)"  # Зеленый полупрозрачный
            )
            self.copy_button.setStyleSheet(success_style)
            
            # Через 1.5 секунды возвращаем обратно
            QtCore.QTimer.singleShot(1500, lambda: self._restore_copy_button(original_text, original_style))
    
    def _restore_copy_button(self, original_text, original_style):
        """Восстановление оригинального вида кнопки"""
        if self.copy_button:
            self.copy_button.setText(original_text)
            self.copy_button.setStyleSheet(original_style)
    
    def fade_out_and_delete(self):
        """
        Плавное исчезновение виджета через прозрачность.
        
        ВАЖНО: Работает одинаково во всех темах (светлая/тёмная).
        Стиль темы НЕ влияет на механизм удаления.
        """
        # На Windows GraphicsOpacityEffect работает медленно - используем упрощённую анимацию
        if IS_WINDOWS:
            # Упрощённая анимация для Windows без GraphicsOpacityEffect
            try:
                # Просто удаляем без эффектов (на Windows могут быть проблемы с repaint)
                self.deleteLater()
            except Exception as e:
                print(f"[FADE_OUT] Ошибка удаления на Windows: {e}")
            return
        
        # Для macOS и Linux - полноценная анимация с opacity
        # Проверяем, существует ли opacity_effect
        if not hasattr(self, 'opacity_effect') or self.opacity_effect is None:
            # Если эффект удалён - создаём новый
            self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self.opacity_effect)
            self.opacity_effect.setOpacity(1.0)
        
        # Дополнительная проверка: проверяем что эффект не был удалён из C++
        try:
            # Пытаемся получить текущую прозрачность - если объект удалён, будет RuntimeError
            current_opacity = self.opacity_effect.opacity()
        except RuntimeError:
            # Объект был удалён на уровне C++ - создаём новый
            self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self.opacity_effect)
            self.opacity_effect.setOpacity(1.0)
        
        # ✅ ТОЛЬКО fade-out прозрачности, БЕЗ изменения высоты
        # Layout сам пересчитает позиции после удаления виджета
        # КРИТИЧНО: Анимация НЕ зависит от темы - работает одинаково везде
        self.fade_out_animation = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out_animation.setDuration(350)  # Плавная анимация
        self.fade_out_animation.setStartValue(1.0)
        self.fade_out_animation.setEndValue(0.0)
        self.fade_out_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)  # Плавное замедление
        
        # Удаляем виджет после завершения fade-out
        def safe_delete():
            try:
                # Останавливаем анимацию перед удалением
                if hasattr(self, 'fade_out_animation') and self.fade_out_animation:
                    self.fade_out_animation.stop()
                    self.fade_out_animation = None
                # Удаляем эффект
                if self.graphicsEffect():
                    self.setGraphicsEffect(None)
                # Обнуляем ссылку на opacity_effect
                if hasattr(self, 'opacity_effect'):
                    self.opacity_effect = None
                # Удаляем виджет
                self.deleteLater()
                print("[FADE_OUT] Системное сообщение плавно удалено")
            except RuntimeError:
                # Объект уже удалён
                print("[FADE_OUT] Объект уже удалён (RuntimeError)")
                pass
            except Exception as e:
                print(f"[FADE_OUT] Неожиданная ошибка при удалении: {e}")
        
        self.fade_out_animation.finished.connect(safe_delete)
        self.fade_out_animation.start()
        
        print("[FADE_OUT] Запущена анимация fade-out (универсальная для всех тем)")


    def _regen_update_nav(self):
        """Обновить кнопки навигации и счётчик после изменения истории."""
        total = len(self._regen_history)
        idx   = self._regen_idx
        show  = total > 1
        
        # Показываем/скрываем group-контейнер целиком
        nav_group = getattr(self, '_regen_nav_group', None)
        if nav_group:
            nav_group.setVisible(show)
        else:
            # Fallback: управляем по отдельности (старый код)
            for w in [self._regen_prev_btn, self._regen_counter, self._regen_next_btn]:
                if w:
                    w.setVisible(show)
        
        if show:
            if self._regen_counter:
                self._regen_counter.setText(f"{idx + 1}/{total}")
            if self._regen_prev_btn:
                self._regen_prev_btn.setEnabled(idx > 0)
            if self._regen_next_btn:
                self._regen_next_btn.setEnabled(idx < total - 1)

    def _regen_go_prev(self):
        """Показать предыдущий вариант ответа."""
        if self._regen_idx > 0:
            self._regen_idx -= 1
            self._regen_apply_entry(self._regen_idx)

    def _regen_go_next(self):
        """Показать следующий вариант ответа."""
        if self._regen_idx < len(self._regen_history) - 1:
            self._regen_idx += 1
            self._regen_apply_entry(self._regen_idx)

    def _regen_apply_entry(self, idx: int):
        """Применить запись из истории: обновить текст, имя модели и счётчик."""
        if idx < 0 or idx >= len(self._regen_history):
            return
        entry = self._regen_history[idx]
        self.text = entry["text"]
        # Обновляем имя модели (при перегенерации через другую модель)
        if entry.get("speaker"):
            self.speaker = entry["speaker"]
        
        # Обновляем текст пузыря
        if hasattr(self, 'message_label') and self.message_label:
            try:
                formatted = format_text_with_markdown_and_math(entry["text"])
            except Exception:
                formatted = entry["text"]
            color = getattr(self, '_speaker_color', '#4CAF50')
            self.message_label.setText(
                f"<b style='color:{color};'>{self.speaker}:</b><br>{formatted}"
            )
        
        self._regen_update_nav()

    def add_regen_entry(self, text: str, thinking_time: float = 0,
                        action_history: list = None, sources: list = None,
                        speaker: str = None):
        """
        Добавить новый вариант в историю перегенерации.
        speaker — имя модели (может отличаться при force_model_key).
        """
        entry = {
            "text": text,
            "thinking_time": thinking_time,
            "action_history": action_history or [],
            "sources": sources or [],
            "speaker": speaker or self.speaker,
        }
        self._regen_history.append(entry)
        self._regen_idx = len(self._regen_history) - 1
        self._regen_apply_entry(self._regen_idx)
        self._regen_update_nav()
        # Восстанавливаем яркость после перегенерации
        self._set_regen_dim(False)
        # ВАЖНО: _persist_regen_history НЕ вызываем здесь — она должна вызываться
        # ПОСЛЕ save_message в handle_response, иначе обновляется старая запись БД.
        print(f"[REGEN_HISTORY] Вариант {self._regen_idx + 1}/{len(self._regen_history)}, модель: {entry['speaker']}")

    def _set_regen_dim(self, dimmed: bool):
        """Затемнить/восстановить пузырь во время перегенерации.
        
        ВАЖНО: после fade-in анимации setGraphicsEffect(None) убивает opacity_effect.
        Поэтому мы всегда создаём НОВЫЙ эффект, а не переиспользуем старый.
        """
        try:
            if dimmed:
                # Создаём свежий эффект и вешаем на виджет
                eff = QtWidgets.QGraphicsOpacityEffect(self)
                self.setGraphicsEffect(eff)
                self.opacity_effect = eff
                eff.setOpacity(1.0)
                anim = QtCore.QPropertyAnimation(eff, b"opacity")
                anim.setDuration(200)
                anim.setStartValue(1.0)
                anim.setEndValue(0.38)
                anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                anim.start()
                self._dim_anim = anim
            else:
                # Берём текущий эффект (может быть нашим dim-эффектом)
                eff = self.graphicsEffect()
                if eff is None:
                    return  # уже чистый, ничего делать не нужно
                cur_opacity = eff.opacity() if hasattr(eff, 'opacity') else 0.38
                anim = QtCore.QPropertyAnimation(eff, b"opacity")
                anim.setDuration(250)
                anim.setStartValue(cur_opacity)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                # После восстановления убираем эффект (иначе он искажает цвета)
                anim.finished.connect(lambda: self.setGraphicsEffect(None))
                anim.start()
                self._dim_anim = anim
        except Exception as e:
            print(f"[DIM] Ошибка затемнения: {e}")

    def _persist_regen_history(self):
        """Сохранить историю перегенерации в БД через main_window."""
        try:
            mw = self.main_window
            if not mw:
                return
            chat_id = getattr(mw, 'current_chat_id', None)
            if not chat_id:
                return
            cm = getattr(mw, 'chat_manager', None)
            if not cm:
                return
            msg_id = cm.get_last_assistant_message_id(chat_id)
            if not msg_id:
                return
            cm.update_regen_history(chat_id, msg_id, self._regen_history)
            print(f"[REGEN_HISTORY] ✓ Сохранено в БД msg_id={msg_id}, вариантов={len(self._regen_history)}")
        except Exception as e:
            print(f"[REGEN_HISTORY] ⚠️ Ошибка сохранения: {e}")

    def regenerate_response(self):
        """Перегенерировать ответ ассистента — показывает меню выбора модели"""
        parent_window = self.window()
        if not hasattr(parent_window, 'regenerate_last_response'):
            return

        # ── Определяем текущую модель и список альтернатив ──────────
        current_key  = llama_handler.CURRENT_AI_MODEL_KEY
        current_name = llama_handler.SUPPORTED_MODELS.get(current_key, ("", "LLaMA 3"))[1]

        # Список всех моделей кроме текущей — для пунктов «перегенерировать через»
        _all_keys  = list(llama_handler.SUPPORTED_MODELS.keys())
        _alt_keys  = [k for k in _all_keys if k != current_key]

        # ── Создаём контекстное меню ─────────────────────────────────
        menu = QtWidgets.QMenu(self)
        menu.setWindowFlags(
            QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint
        )
        if not IS_WINDOWS:
            menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)

        is_dark = getattr(parent_window, 'current_theme', 'dark') == 'dark'

        if is_dark:
            menu.setStyleSheet("""
                QMenu {
                    background: rgba(28, 28, 32, 0.98);
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 10px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 7px 16px;
                    border-radius: 7px;
                    color: #e0e0e0;
                    font-size: 13px;
                    font-weight: 500;
                    margin: 1px;
                    background: transparent;
                }
                QMenu::item:selected {
                    background: rgba(60, 60, 75, 0.9);
                    color: #ffffff;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(80, 80, 100, 0.4);
                    margin: 2px 8px;
                }
            """)
        else:
            menu.setStyleSheet("""
                QMenu {
                    background: rgba(255, 255, 255, 0.98);
                    border: 1px solid rgba(200, 200, 215, 0.9);
                    border-radius: 10px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 7px 16px;
                    border-radius: 7px;
                    color: #1a202c;
                    font-size: 13px;
                    font-weight: 500;
                    margin: 1px;
                    background: transparent;
                }
                QMenu::item:selected {
                    background: rgba(230, 230, 245, 0.95);
                    color: #0f172a;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(180, 185, 200, 0.5);
                    margin: 2px 8px;
                }
            """)

        act_same  = menu.addAction(f"🔄  Перегенерировать  ({current_name})")
        menu.addSeparator()

        # Динамические пункты «перегенерировать через <другую модель>»
        _alt_actions = {}
        for _alt_key in _alt_keys:
            _alt_display = llama_handler.SUPPORTED_MODELS.get(_alt_key, ("", _alt_key))[1]
            _installed   = check_model_in_ollama(
                llama_handler.SUPPORTED_MODELS.get(_alt_key, (_alt_key,))[0]
            )
            _suffix = "" if _installed else "  ↓ (не скачана)"
            _act = menu.addAction(f"🔀  Перегенерировать через  {_alt_display}{_suffix}")
            _alt_actions[_act] = (_alt_key, _installed, _alt_display)

        # ── Показываем меню рядом с кнопкой ─────────────────────────
        btn = self.regenerate_button
        if btn:
            pos = btn.mapToGlobal(QtCore.QPoint(0, btn.height() + 4))
        else:
            pos = QtGui.QCursor.pos()

        chosen = menu.exec(pos)

        if chosen == act_same:
            parent_window.regenerate_last_response()
        elif chosen in _alt_actions:
            _target_key, _is_installed, _target_display = _alt_actions[chosen]
            if _is_installed:
                parent_window.regenerate_last_response(force_model_key=_target_key)
            else:
                # Модель не скачана — предлагаем скачать
                reply = QtWidgets.QMessageBox.question(
                    self.window(),
                    f"{_target_display} не установлена",
                    f"⚠️ {_target_display} ещё не скачана.\n\n"
                    f"Хотите скачать её сейчас?",
                    QtWidgets.QMessageBox.StandardButton.Yes |
                    QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.Yes,
                )
                if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                    _pw = self.window()
                    if hasattr(_pw, '_start_model_download'):
                        _pw._start_model_download(_target_key)
    
    def edit_message(self):
        """Редактировать сообщение пользователя"""
        parent_window = self.window()
        if hasattr(parent_window, 'edit_last_message'):
            parent_window.edit_last_message(self.text)
    

# -------------------------
# Worker
# -------------------------

    def open_attached_file(self, file_name):
        """Открыть прикреплённый файл при клике.
        
        Если передан полный путь — используем его напрямую.
        Если только имя файла (старые сообщения из БД) — ищем по имени в known paths.
        Для изображений показывает мини-просмотрщик внутри приложения.
        """
        print(f"[FILE_OPEN] Клик по файлу: {file_name}")

        # ── 1. Определяем реальный путь ────────────────────────────────
        # Если это уже абсолютный путь — используем как есть
        if os.path.isabs(file_name) and os.path.exists(file_name):
            file_path = file_name
        else:
            # Старые записи из БД содержат только basename — ищем в текущих attached_files
            file_path = None
            if self.main_window and hasattr(self.main_window, 'attached_files'):
                for fp in self.main_window.attached_files:
                    if os.path.basename(fp) == os.path.basename(file_name):
                        file_path = fp
                        break
            # Последняя попытка — относительный путь как есть
            if not file_path:
                file_path = os.path.abspath(file_name)

        file_path = os.path.normpath(file_path)
        print(f"[FILE_OPEN] Путь: {file_path}")

        # ── 2. Проверяем существование ──────────────────────────────────
        if not os.path.exists(file_path):
            print(f"[FILE_OPEN] ✗ Не найден: {file_path}")
            QtWidgets.QMessageBox.warning(
                self, "Файл не найден",
                f"Файл не найден по пути:\n{file_path}\n\n"
                f"Возможно, файл был перемещён или удалён.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            return

        # ── 3. Изображения — показываем мини-просмотрщик ───────────────
        if is_image_file(file_path):
            print(f"[FILE_OPEN] Открываю изображение в просмотрщике")
            self._show_image_viewer(file_path)
            return

        # ── 4. Текстовые файлы — мини-просмотрщик внутри приложения ──────
        if is_text_file(file_path):
            print(f"[FILE_OPEN] Открываю текстовый файл в просмотрщике")
            self._show_text_viewer(file_path)
            return

        # ── 5. Остальные файлы — системное приложение ──────────────────
        print(f"[FILE_OPEN] ✓ Открываю в системном приложении: {file_path}")
        try:
            if sys.platform == 'darwin':
                subprocess.run(['open', file_path], check=True)
            elif sys.platform == 'win32':
                os.startfile(file_path)
            else:
                subprocess.run(['xdg-open', file_path], check=True)
            print(f"[FILE_OPEN] ✅ Открыт успешно")
        except Exception as e:
            print(f"[FILE_OPEN] ✗ Ошибка: {e}")
            QtWidgets.QMessageBox.warning(
                self, "Ошибка открытия",
                f"Не удалось открыть файл:\n{file_path}\n\n{e}",
                QtWidgets.QMessageBox.StandardButton.Ok
            )

    def _show_image_viewer(self, file_path: str):
        """Мини-просмотрщик изображений — показывает фото в окошке внутри приложения."""
        viewer = _ImageViewerDialog(file_path, parent=self)
        viewer.exec()

    def _show_text_viewer(self, file_path: str):
        """Мини-просмотрщик текстовых файлов."""
        viewer = _TextViewerDialog(file_path, parent=self)
        viewer.exec()

    def _preview_file(self, file_path: str):
        """Открывает предпросмотр файла: изображение или текст."""
        if is_image_file(file_path):
            self._show_image_viewer(file_path)
        elif is_text_file(file_path):
            self._show_text_viewer(file_path)
        else:
            self.open_file(file_path)



# ═══════════════════════════════════════════════════════════════════════════
# МИНИ-ПРОСМОТРЩИК ИЗОБРАЖЕНИЙ
# ═══════════════════════════════════════════════════════════════════════════

class _ImageViewerDialog(QtWidgets.QDialog):
    """Мини-окно для просмотра изображений с zoom/pan."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle(os.path.basename(file_path))
        self.setModal(True)
        self.setMinimumSize(400, 300)
        self.resize(800, 600)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self._pixmap_orig = QtGui.QPixmap(file_path)
        if self._pixmap_orig.isNull():
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Не удалось загрузить изображение.")
            QtCore.QTimer.singleShot(0, self.close)
            return
        self._build_ui()
        QtCore.QTimer.singleShot(50, self._fit_to_window)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._canvas = _ImageCanvas(self._pixmap_orig, self)
        layout.addWidget(self._canvas, stretch=1)

        bar = QtWidgets.QWidget()
        bar.setStyleSheet("background:#1a1b2e;border-top:1px solid rgba(102,126,234,0.25);")
        bar.setFixedHeight(48)
        bl = QtWidgets.QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(10)

        path_lbl = QtWidgets.QLabel(self.file_path)
        path_lbl.setStyleSheet("color:rgba(180,185,220,0.7);font-size:11px;")
        bl.addWidget(path_lbl, stretch=1)

        btn_style = ("QPushButton{color:white;background:rgba(102,126,234,0.25);"
                     "border:1px solid rgba(102,126,234,0.4);border-radius:8px;"
                     "padding:5px 14px;font-size:13px;}"
                     "QPushButton:hover{background:rgba(102,126,234,0.45);}"
                     "QPushButton:pressed{background:rgba(102,126,234,0.6);}")

        for label, slot in [("⊡ По размеру", self._fit_to_window),
                             ("↗ В приложении", self._open_external),
                             ("✕ Закрыть", self.close)]:
            btn = QtWidgets.QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(slot)
            bl.addWidget(btn)

        layout.addWidget(bar)
        self._canvas.request_fit = self._fit_to_window
        self.setStyleSheet("QDialog{background:#0d0e1a;}")

    def _fit_to_window(self):
        if self._pixmap_orig.isNull():
            return
        cw, ch = self._canvas.width(), self._canvas.height()
        pw, ph = self._pixmap_orig.width(), self._pixmap_orig.height()
        if pw == 0 or ph == 0 or cw == 0 or ch == 0:
            return
        scale = min(cw / pw, ch / ph) * 0.95
        self._canvas.set_transform(scale, QtCore.QPointF(0, 0))

    def _open_external(self):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", self.file_path], check=True)
            elif sys.platform == "win32":
                os.startfile(self.file_path)
            else:
                subprocess.run(["xdg-open", self.file_path], check=True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Не удалось открыть:\n{e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0, self._fit_to_window)


class _ImageCanvas(QtWidgets.QWidget):
    """Холст с zoom (колесо мыши) и pan (перетаскивание)."""

    def __init__(self, pixmap: QtGui.QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._scale = 1.0
        self._offset = QtCore.QPointF(0, 0)
        self._drag_start = None
        self._drag_offset_start = None
        self.request_fit = None
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.OpenHandCursor))

    def set_transform(self, scale: float, offset: QtCore.QPointF):
        self._scale = scale
        self._offset = offset
        self.update()

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        cx = self.width() / 2 + self._offset.x()
        cy = self.height() / 2 + self._offset.y()
        w = self._pixmap.width() * self._scale
        h = self._pixmap.height() * self._scale
        rect = QtCore.QRectF(cx - w / 2, cy - h / 2, w, h)
        painter.drawPixmap(rect, self._pixmap, QtCore.QRectF(self._pixmap.rect()))
        painter.end()

    def wheelEvent(self, event):
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self._scale = max(0.05, min(self._scale * factor, 20.0))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_start = event.position()
            self._drag_offset_start = QtCore.QPointF(self._offset)
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            delta = event.position() - self._drag_start
            self._offset = self._drag_offset_start + delta
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.OpenHandCursor))

    def mouseDoubleClickEvent(self, event):
        if self.request_fit:
            self.request_fit()



# ═══════════════════════════════════════════════════════════════════════════
# МИНИ-ПРОСМОТРЩИК ТЕКСТОВЫХ ФАЙЛОВ
# ═══════════════════════════════════════════════════════════════════════════

_TEXT_EXTENSIONS = {
    '.txt', '.md', '.py', '.js', '.ts', '.html', '.css', '.json', '.xml',
    '.csv', '.log', '.yaml', '.yml', '.ini', '.cfg', '.toml', '.sh',
    '.bat', '.c', '.cpp', '.h', '.java', '.rs', '.go', '.php', '.rb',
    '.swift', '.kt', '.sql', '.env', '.gitignore',
}

def is_text_file(file_path: str) -> bool:
    """Возвращает True если файл — текстовый (по расширению)."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in _TEXT_EXTENSIONS


class _TextViewerDialog(QtWidgets.QDialog):
    """Мини-окно для просмотра текстовых файлов."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle(os.path.basename(file_path))
        self.setModal(True)
        self.setMinimumSize(500, 400)
        self.resize(800, 600)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self._build_ui()
        self._load_content()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._text_edit = QtWidgets.QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont((QtGui.QFont("Cascadia Code", 12) if IS_WINDOWS else QtGui.QFont("Menlo", 12)))
        self._text_edit.setStyleSheet(
            "QPlainTextEdit { background:#0d0e1a; color:#c8d0e7; "
            "border:none; padding:12px; }"
        )
        layout.addWidget(self._text_edit, stretch=1)

        bar = QtWidgets.QWidget()
        bar.setStyleSheet("background:#1a1b2e;border-top:1px solid rgba(102,126,234,0.25);")
        bar.setFixedHeight(48)
        bl = QtWidgets.QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(10)

        path_lbl = QtWidgets.QLabel(self.file_path)
        path_lbl.setStyleSheet("color:rgba(180,185,220,0.7);font-size:11px;")
        bl.addWidget(path_lbl, stretch=1)

        btn_style = (
            "QPushButton{color:white;background:rgba(102,126,234,0.25);"
            "border:1px solid rgba(102,126,234,0.4);border-radius:8px;"
            "padding:5px 14px;font-size:13px;}"
            "QPushButton:hover{background:rgba(102,126,234,0.45);}"
            "QPushButton:pressed{background:rgba(102,126,234,0.6);}"
        )
        for label, slot in [("↗ В приложении", self._open_external),
                              ("✕ Закрыть", self.close)]:
            btn = QtWidgets.QPushButton(label)
            btn.setStyleSheet(btn_style)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(slot)
            bl.addWidget(btn)

        layout.addWidget(bar)
        self.setStyleSheet("QDialog{background:#0d0e1a;}")

    def _load_content(self):
        try:
            for enc in ("utf-8", "cp1251", "latin-1"):
                try:
                    with open(self.file_path, "r", encoding=enc) as f:
                        text = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = "[Не удалось прочитать файл — неизвестная кодировка]"
            # Ограничиваем до 200 КБ для производительности
            if len(text) > 200_000:
                text = text[:200_000] + "\n\n[... файл обрезан до 200 КБ ...]"
            self._text_edit.setPlainText(text)
        except Exception as e:
            self._text_edit.setPlainText(f"[Ошибка чтения файла: {e}]")

    def _open_external(self):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", self.file_path], check=True)
            elif sys.platform == "win32":
                os.startfile(self.file_path)
            else:
                subprocess.run(["xdg-open", self.file_path], check=True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Не удалось открыть:\n{e}")


class WorkerSignals(QtCore.QObject):
    # (response_text, list of (title, url) source tuples)
    finished = QtCore.pyqtSignal(str, list)

class AIWorker(QtCore.QRunnable):
    def __init__(self, user_message: str, current_language: str, deep_thinking: bool, use_search: bool, should_forget: bool = False, chat_manager=None, chat_id=None, file_paths: list = None, ai_mode: str = AI_MODE_FAST, model_key_override: str = None):
        super().__init__()
        self.user_message = user_message
        self.current_language = current_language
        self.deep_thinking = deep_thinking
        self.use_search = use_search
        self.should_forget = should_forget
        self.chat_manager = chat_manager
        self.chat_id = chat_id
        self.file_paths = file_paths if file_paths else []
        self.ai_mode = ai_mode
        self._cancelled = False
        # Уникальный ID запроса — для защиты от "призраков" после стопа
        self.request_id = id(self)
        self.signals = WorkerSignals()
        # model_key_override — явная модель для перегенерации другой моделью
        # Если не передан — берём текущую активную модель из глобала
        self.model_key = model_key_override if model_key_override is not None else llama_handler.CURRENT_AI_MODEL_KEY

    @QtCore.pyqtSlot()
    def run(self):
        try:
            if llama_handler._APP_SHUTTING_DOWN or self._cancelled:
                return
            response, sources = get_ai_response(
                self.user_message,
                self.current_language,
                self.deep_thinking,
                self.use_search,
                self.should_forget,
                self.chat_manager,
                self.chat_id,
                self.file_paths,
                self.ai_mode,
                self.model_key   # ← явная передача модели
            )
            # Проверяем ещё раз после долгого ожидания ответа от Ollama
            if self._cancelled or llama_handler._APP_SHUTTING_DOWN:
                print(f"[WORKER] ⚠️ Запрос {self.request_id} отменён — ответ сброшен")
                return
            if hasattr(self, 'signals') and self.signals is not None:
                try:
                    self.signals.finished.emit(response, sources)
                except RuntimeError:
                    pass
        except Exception as e:
            if self._cancelled:
                return
            if hasattr(self, 'signals') and self.signals is not None:
                try:
                    self.signals.finished.emit(f"[Ошибка] {e}", [])
                except RuntimeError:
                    pass

# -------------------------
# Main Window
# -------------------------

# ═══════════════════════════════════════════════════════════════════════════
# БАЗОВЫЙ КЛАСС: NoFocusButton
# Кнопка без focus ring — переопределяет paintEvent чтобы убрать системный
# focus rect, который не убирается через QSS на всех платформах
# ═══════════════════════════════════════════════════════════════════════════

class NoFocusButton(QtWidgets.QPushButton):
    """QPushButton без системного focus ring на всех платформах."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    
    def paintEvent(self, event):
        try:
            opt = QtWidgets.QStyleOptionButton()
            self.initStyleOption(opt)
            opt.state &= ~QtWidgets.QStyle.StateFlag.State_HasFocus
            painter = QtGui.QPainter(self)
            if not painter.isActive():
                return
            self.style().drawControl(QtWidgets.QStyle.ControlElement.CE_PushButton, opt, painter, self)
            painter.end()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# НОВЫЙ КОМПОНЕНТ 1: SCROLL TO BOTTOM BUTTON
# Floating overlay кнопка "⬇ вниз" - НЕ участвует в layout
# ═══════════════════════════════════════════════════════════════════════════

class ScrollToBottomButton(QtWidgets.QPushButton):
    """
    Floating overlay кнопка "⬇ вниз" для скроллинга к низу.
    
    КРИТИЧЕСКИЕ ПРАВИЛА:
    - НЕ участвует в layout сообщений
    - НЕ вызывает автоскролл
    - Только индикатор наличия непрочитанных сообщений внизу
    - Позиция: overlay поверх scroll_area
    """
    
    def __init__(self, parent=None):
        super().__init__("⬇", parent)
        
        self.setObjectName("scrollToBottomBtn")
        self.setFixedSize(50, 50)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        # Изначально скрыта
        self.hide()
        
        # Применяем стиль по умолчанию (светлая тема + glass)
        # На этом этапе добавится тень через graphicsEffect
        self.apply_theme_styles(theme="light", liquid_glass=True)
        
        # ═══════════════════════════════════════════════════════════════
        # ПЛАВНОЕ ПОЯВЛЕНИЕ/ИСЧЕЗНОВЕНИЕ через opacity
        # ═══════════════════════════════════════════════════════════════
        # ВАЖНО: Создаём ПОСЛЕ apply_theme_styles, но используем CSS drop-shadow вместо graphicsEffect
        # так как graphicsEffect можно установить только один
        
        # Создаём эффект прозрачности (заменит тень)
        self.opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)  # Изначально невидима
        
        # Анимация fade in/out
        self.fade_animation = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(400)  # 400ms - более плавная и приятная анимация
        self.fade_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutExpo)  # Более естественная кривая
        
        # Флаг текущего состояния видимости (для предотвращения лишних анимаций)
        self._is_visible_animated = False
    
    def apply_theme_styles(self, theme: str = "light", liquid_glass: bool = True):
        """
        Применить стили в зависимости от темы и liquid glass.
        
        Вызывается при изменении настроек темы.
        """
        if theme == "dark":
            if liquid_glass:
                # ТЁМНАЯ ТЕМА + СТЕКЛО - тёмное полупрозрачное стекло
                bg_start = "rgba(35, 35, 40, 0.75)"
                bg_end = "rgba(28, 28, 32, 0.75)"
                border = "rgba(50, 50, 55, 0.6)"
                hover_bg_start = "rgba(45, 45, 50, 0.85)"
                hover_bg_end = "rgba(38, 38, 42, 0.85)"
                hover_border = "rgba(139, 92, 246, 0.5)"
                text_color = "#e6e6e6"
                shadow_color = "rgba(0, 0, 0, 0.7)"
            else:
                # ТЁМНАЯ ТЕМА БЕЗ СТЕКЛА - матовый тёмный
                bg_start = "rgb(43, 43, 48)"
                bg_end = "rgb(38, 38, 42)"
                border = "rgba(60, 60, 65, 0.95)"
                hover_bg_start = "rgb(53, 53, 58)"
                hover_bg_end = "rgb(48, 48, 52)"
                hover_border = "rgba(139, 92, 246, 0.7)"
                text_color = "#f0f0f0"
                shadow_color = "rgba(0, 0, 0, 0.5)"
        else:
            if liquid_glass:
                # СВЕТЛАЯ ТЕМА + СТЕКЛО - светлое полупрозрачное стекло
                bg_start = "rgba(255, 255, 255, 0.75)"
                bg_end = "rgba(255, 255, 255, 0.65)"
                border = "rgba(255, 255, 255, 0.85)"
                hover_bg_start = "rgba(255, 255, 255, 0.90)"
                hover_bg_end = "rgba(255, 255, 255, 0.80)"
                hover_border = "rgba(102, 126, 234, 0.65)"
                text_color = "#2d3748"
                shadow_color = "rgba(0, 0, 0, 0.15)"
            else:
                # СВЕТЛАЯ ТЕМА БЕЗ СТЕКЛА - матовый светлый
                bg_start = "rgb(242, 242, 245)"
                bg_end = "rgb(235, 235, 240)"
                border = "rgba(210, 210, 215, 0.95)"
                hover_bg_start = "rgb(235, 235, 240)"
                hover_bg_end = "rgb(225, 225, 230)"
                hover_border = "rgba(102, 126, 234, 0.8)"
                text_color = "#1a1a1a"
                shadow_color = "rgba(0, 0, 0, 0.2)"
        
        self.setStyleSheet(f"""
            #scrollToBottomBtn {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {bg_start},
                    stop:1 {bg_end});
                border: 1px solid {border};
                border-radius: 25px;
                color: {text_color};
                font-size: 20px;
                font-weight: bold;
            }}
            #scrollToBottomBtn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {hover_bg_start},
                    stop:1 {hover_bg_end});
                border: 1px solid {hover_border};
            }}
        """)
        # Тень НЕ добавляем, так как используем opacity_effect для анимации
    
    def update_position(self, parent_width, parent_height):
        """
        Обновить позицию кнопки (центр снизу).
        НЕ вызывается автоматически - только вручную при resize.
        """
        x = (parent_width - self.width()) // 2
        y = parent_height - self.height() - 90  # 90px от низа (не налезает на input bar)
        self.move(x, y)
        self.raise_()
    
    def smooth_show(self):
        """
        Плавное появление кнопки через fade in анимацию.
        
        ОПТИМИЗАЦИЯ: Проверяем текущее состояние чтобы не запускать
        лишние анимации если кнопка уже видна.
        """
        # Если кнопка уже показана - ничего не делаем
        if self._is_visible_animated:
            return
        
        # Показываем виджет (но он невидим из-за opacity=0)
        if not self.isVisible():
            self.show()
        
        # Запускаем fade in анимацию
        self.fade_animation.stop()
        self.fade_animation.setStartValue(self.opacity_effect.opacity())
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()
        
        self._is_visible_animated = True
    
    def smooth_hide(self):
        """
        Плавное исчезновение кнопки через fade out анимацию.
        
        ОПТИМИЗАЦИЯ: Проверяем текущее состояние чтобы не запускать
        лишние анимации если кнопка уже скрыта.
        """
        # Если кнопка уже скрыта - ничего не делаем
        if not self._is_visible_animated:
            return
        
        # Запускаем fade out анимацию
        self.fade_animation.stop()
        self.fade_animation.setStartValue(self.opacity_effect.opacity())
        self.fade_animation.setEndValue(0.0)
        
        # После завершения анимации скрываем виджет
        def on_fade_out_finished():
            if self.opacity_effect.opacity() == 0.0:
                self.hide()
        
        # Отключаем старый обработчик если был
        try:
            self.fade_animation.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        
        self.fade_animation.finished.connect(on_fade_out_finished)
        self.fade_animation.start()
        
        self._is_visible_animated = False


# ═══════════════════════════════════════════════════════════════════════════
# НОВЫЙ КОМПОНЕНТ 2: SETTINGS VIEW
# Экран настроек - замена chat_area
# ═══════════════════════════════════════════════════════════════════════════

class SettingsView(QtWidgets.QWidget):
    """
    Экран настроек приложения.
    
    КРИТИЧЕСКИЕ ПРАВИЛА:
    - НЕ влияет на messages_layout
    - НЕ создаёт новое окно
    - Заменяет содержимое chat_container через QStackedWidget
    - Sidebar и input bar остаются видимыми
    """
    
    # Сигналы
    settings_applied = QtCore.pyqtSignal(dict)
    close_requested = QtCore.pyqtSignal()
    delete_all_chats_requested = QtCore.pyqtSignal()  # Новый сигнал для удаления всех чатов
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("settingsView")
        
        # Текущие настройки (сохранённые и применённые)
        self.current_settings = {
            "theme": "light",
            "liquid_glass": True,
        }
        
        # Временные настройки (pending - до нажатия "Применить")
        self.pending_settings = {
            "theme": "light",
            "liquid_glass": True,
        }
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Инициализация UI"""
        
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(20)
        
        # Заголовок
        title = QtWidgets.QLabel("⚙️ Настройки")
        title.setObjectName("settingsTitle")
        title.setFont(_apple_font(28, weight=QtGui.QFont.Weight.Bold))
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)
        
        # Контейнер настроек
        settings_container = QtWidgets.QWidget()
        settings_container.setObjectName("settingsContainer")
        settings_layout = QtWidgets.QVBoxLayout(settings_container)
        settings_layout.setSpacing(16)
        
        # ═══════════════════════════════════════════════
        # НАСТРОЙКА 1: Тема
        # ═══════════════════════════════════════════════
        theme_group = self.create_setting_group(
            "Тема оформления",
            "Переключение между светлой и тёмной темой"
        )
        
        theme_layout = QtWidgets.QHBoxLayout()
        theme_layout.setSpacing(15)
        
        self.theme_light_btn = QtWidgets.QPushButton("☀️ Светлая")
        self.theme_light_btn.setObjectName("themeLightBtn")
        self.theme_light_btn.setCheckable(True)
        self.theme_light_btn.setChecked(True)
        self.theme_light_btn.clicked.connect(lambda: self.set_theme("light"))
        
        self.theme_dark_btn = QtWidgets.QPushButton("🌙 Тёмная")
        self.theme_dark_btn.setObjectName("themeDarkBtn")
        self.theme_dark_btn.setCheckable(True)
        self.theme_dark_btn.clicked.connect(lambda: self.set_theme("dark"))
        
        theme_layout.addWidget(self.theme_light_btn)
        theme_layout.addWidget(self.theme_dark_btn)
        
        theme_group.layout().addLayout(theme_layout)
        settings_layout.addWidget(theme_group)
        
        # ═══════════════════════════════════════════════
        # НАСТРОЙКА 2: Liquid Glass
        # ═══════════════════════════════════════════════
        glass_group = self.create_setting_group(
            "Liquid Glass",
            "Стеклянный эффект для элементов интерфейса"
        )

        # Превью пузырей — точные копии настоящих пузырей MessageWidget
        preview_layout = QtWidgets.QHBoxLayout()
        preview_layout.setSpacing(20)
        preview_layout.setContentsMargins(0, 8, 0, 8)

        # Определяем текущую тему для превью
        try:
            if os.path.exists("app_settings.json"):
                with open("app_settings.json", "r", encoding="utf-8") as _f:
                    _s = json.load(_f)
                    _theme = _s.get("theme", "light")
            else:
                _theme = "light"
        except Exception:
            _theme = "light"

        self.preview_glass_bubble = self._make_preview_bubble(liquid_glass=True, theme=_theme, label="Со стеклом")
        self.preview_matte_bubble = self._make_preview_bubble(liquid_glass=False, theme=_theme, label="Без стекла")

        preview_layout.addWidget(self.preview_glass_bubble)
        preview_layout.addWidget(self.preview_matte_bubble)

        glass_group.layout().addLayout(preview_layout)

        glass_layout = QtWidgets.QHBoxLayout()
        glass_layout.setSpacing(15)
        self.glass_on_btn = QtWidgets.QPushButton("🪟 Включено")
        self.glass_on_btn.setObjectName("glassOnBtn")
        self.glass_on_btn.setCheckable(True)
        self.glass_on_btn.setChecked(True)
        self.glass_on_btn.clicked.connect(lambda: self.set_liquid_glass(True))
        self.glass_off_btn = QtWidgets.QPushButton("🔲 Выключено")
        self.glass_off_btn.setObjectName("glassOffBtn")
        self.glass_off_btn.setCheckable(True)
        self.glass_off_btn.clicked.connect(lambda: self.set_liquid_glass(False))
        glass_layout.addWidget(self.glass_on_btn)
        glass_layout.addWidget(self.glass_off_btn)
        glass_group.layout().addLayout(glass_layout)
        settings_layout.addWidget(glass_group)
        
        # ═══════════════════════════════════════════════
        # ОПАСНАЯ ЗОНА: Удаление всех чатов
        # ═══════════════════════════════════════════════
        danger_group = self.create_setting_group(
            "⚠️ Опасная зона",
            "Необратимые действия. Будьте осторожны!"
        )
        
        delete_all_layout = QtWidgets.QVBoxLayout()
        delete_all_layout.setSpacing(10)
        
        self.delete_all_chats_btn = QtWidgets.QPushButton("🗑️ Удалить все чаты")
        self.delete_all_chats_btn.setObjectName("deleteAllChatsBtn")
        self.delete_all_chats_btn.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Medium))
        self.delete_all_chats_btn.setMinimumHeight(45)
        self.delete_all_chats_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.delete_all_chats_btn.clicked.connect(self.request_delete_all_chats)
        
        delete_all_layout.addWidget(self.delete_all_chats_btn)
        
        danger_group.layout().addLayout(delete_all_layout)
        settings_layout.addWidget(danger_group)
        
        # Оборачиваем settings_container в QScrollArea,
        # чтобы контент прокручивался, а не растягивал окно
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidget(settings_container)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll_area.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        main_layout.addWidget(scroll_area, stretch=1)
        
        # ═══════════════════════════════════════════════
        # КНОПКИ ДЕЙСТВИЙ
        # ═══════════════════════════════════════════════
        actions_layout = QtWidgets.QHBoxLayout()
        actions_layout.setSpacing(15)
        
        back_btn = QtWidgets.QPushButton("← Назад к чату")
        back_btn.setObjectName("settingsBackBtn")
        back_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        back_btn.setMinimumHeight(50)
        back_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        back_btn.clicked.connect(self.close_requested.emit)
        
        apply_btn = QtWidgets.QPushButton("✓ Применить")
        apply_btn.setObjectName("settingsApplyBtn")
        apply_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Bold))
        apply_btn.setMinimumHeight(50)
        apply_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        apply_btn.clicked.connect(self.apply_settings)
        
        actions_layout.addWidget(back_btn)
        actions_layout.addWidget(apply_btn)
        
        main_layout.addLayout(actions_layout)
        
        self.apply_settings_styles()
    
    def create_setting_group(self, title: str, description: str) -> QtWidgets.QGroupBox:
        """Создать группу настроек"""
        
        group = QtWidgets.QGroupBox()
        group.setObjectName("settingGroup")
        
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(12)
        
        title_label = QtWidgets.QLabel(title)
        title_label.setFont(_apple_font(18, weight=QtGui.QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        desc_label = QtWidgets.QLabel(description)
        desc_label.setObjectName("descLabel")
        desc_label.setFont(_apple_font(13))
        desc_label.setStyleSheet("color: #475569;")
        layout.addWidget(desc_label)
        
        return group
    
    def _make_preview_bubble(self, liquid_glass: bool, theme: str, label: str) -> QtWidgets.QWidget:
        """
        Создаёт превью-пузырь. Оба пузыря одинаковой структуры для симметрии.
        Оба имеют обёртку-фон: у стеклянного — контрастный, у матового — прозрачный.
        objectNames совпадают с apply_settings_styles.
        """
        prefix = "Glass" if liquid_glass else "Matte"

        # Внешний контейнер (подпись + обёртка + пузырь) — одинаковая структура для обоих
        outer = QtWidgets.QWidget()
        outer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred
        )
        outer_layout = QtWidgets.QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(6)

        # Подпись
        lbl = QtWidgets.QLabel(label)
        lbl.setObjectName("previewColLabel")
        lbl.setFont(_apple_font(11))
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        outer_layout.addWidget(lbl)

        # Обёртка — одинаковая у обоих (симметрия). У стеклянного — с фоном (через CSS),
        # у матового — прозрачная. Padding одинаковый.
        wrapper = QtWidgets.QWidget()
        wrapper.setObjectName(f"preview{prefix}Bg")
        wrapper_layout = QtWidgets.QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(10, 10, 10, 10)

        # Пузырь — objectName совпадает с apply_settings_styles
        bubble = QtWidgets.QWidget()
        bubble.setObjectName(f"preview{prefix}Bubble")
        bubble.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred
        )
        bubble_layout = QtWidgets.QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(20, 16, 20, 16)
        bubble_layout.setSpacing(4)

        # Имя спикера
        name_lbl = QtWidgets.QLabel("LLaMA 3:")
        name_lbl.setObjectName(f"preview{prefix}Name")
        name_lbl.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Bold))
        bubble_layout.addWidget(name_lbl)

        # Текст
        msg_text = "Привет! Это стеклянный стиль." if liquid_glass else "Привет! Это матовый стиль."
        msg_lbl = QtWidgets.QLabel(msg_text)
        msg_lbl.setObjectName(f"preview{prefix}Text")
        msg_lbl.setFont(_apple_font(13))
        msg_lbl.setWordWrap(True)
        bubble_layout.addWidget(msg_lbl)

        wrapper_layout.addWidget(bubble)
        outer_layout.addWidget(wrapper)
        return outer

    def set_theme(self, theme: str):
        """
        Установить тему ВИЗУАЛЬНО (pending state).
        
        ВАЖНО: НЕ применяет стили к приложению!
        Только меняет визуальное состояние кнопок выбора.
        Реальное применение происходит при нажатии "Применить".
        """
        # Сохраняем в pending settings
        self.pending_settings["theme"] = theme
        
        # Обновляем ТОЛЬКО визуальное состояние кнопок
        self.theme_light_btn.setChecked(theme == "light")
        self.theme_dark_btn.setChecked(theme == "dark")
        
        # Обновляем превью под новую тему
        self.apply_settings_styles()
        print(f"[SETTINGS] Выбрана тема: {theme} (pending, не применено)")
    
    def set_liquid_glass(self, enabled: bool):
        """Установить liquid glass (pending state)."""
        self.pending_settings["liquid_glass"] = enabled
        self.glass_on_btn.setChecked(enabled)
        self.glass_off_btn.setChecked(not enabled)
        self.apply_settings_styles()
        print(f"[SETTINGS] Liquid Glass: {'вкл' if enabled else 'выкл'} (pending)")
    
    def load_settings(self):
        """Загрузить сохранённые настройки"""
        try:
            if os.path.exists("app_settings.json"):
                with open("app_settings.json", "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.current_settings.update(saved)
                    # Копируем в pending settings
                    self.pending_settings.update(saved)
        except Exception as e:
            print(f"[SETTINGS] Ошибка загрузки: {e}")
        
        # Устанавливаем визуальное состояние кнопок согласно current settings
        theme = self.current_settings.get("theme", "light")
        liquid_glass = self.current_settings.get("liquid_glass", True)
        self.theme_light_btn.setChecked(theme == "light")
        self.theme_dark_btn.setChecked(theme == "dark")
        self.glass_on_btn.setChecked(liquid_glass)
        self.glass_off_btn.setChecked(not liquid_glass)
        
        # Применяем стили к самому окну настроек
        self.apply_settings_styles()
    
    def save_settings(self):
        """Сохранить настройки"""
        try:
            with open("app_settings.json", "w", encoding="utf-8") as f:
                json.dump(self.current_settings, f, indent=2)
            print("[SETTINGS] ✓ Настройки сохранены")
        except Exception as e:
            print(f"[SETTINGS] ✗ Ошибка сохранения: {e}")
    
    def request_delete_all_chats(self):
        """Запросить подтверждение удаления всех чатов"""
        print("[SETTINGS] Запрос на удаление всех чатов")
        self.delete_all_chats_requested.emit()
    
    def update_delete_all_btn_state(self, has_chats_with_messages: bool):
        """
        Обновить состояние кнопки 'Удалить все чаты'.
        Отключает кнопку если нет ни одного чата с сообщениями.
        """
        if hasattr(self, 'delete_all_chats_btn'):
            self.delete_all_chats_btn.setEnabled(has_chats_with_messages)
            if has_chats_with_messages:
                self.delete_all_chats_btn.setCursor(
                    QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
                self.delete_all_chats_btn.setToolTip("")
            else:
                self.delete_all_chats_btn.setCursor(
                    QtGui.QCursor(QtCore.Qt.CursorShape.ForbiddenCursor))
                self.delete_all_chats_btn.setToolTip("Нет чатов для удаления")
    
    def apply_settings(self):
        """
        Применить настройки к приложению.
        
        ВАЖНО: Это единственное место где pending_settings копируется в current_settings
        и отправляется сигнал settings_applied.
        """
        # Копируем pending settings в current settings
        self.current_settings.update(self.pending_settings)
        
        # Сохраняем в файл
        self.save_settings()
        
        # Отправляем сигнал главному окну для применения стилей
        self.settings_applied.emit(self.current_settings)
        
        print(f"[SETTINGS] ✓ Настройки применены: {self.current_settings}")
        # НЕ закрываем настройки автоматически - пользователь сам решает когда вернуться
    
    def apply_settings_styles(self):
        """Применить стили с поддержкой тем"""
        
        # Определяем текущую тему из настроек
        theme = self.current_settings.get("theme", "light")
        liquid_glass = self.current_settings.get("liquid_glass", True)
        
        print(f"[SETTINGS_VIEW] apply_settings_styles: theme={theme}, liquid_glass={liquid_glass}")
        
        if theme == "dark":
            if liquid_glass:
                # ТЁМНАЯ ТЕМА + СТЕКЛО - тёмное стекло
                colors = {
                    "bg": "rgba(24, 24, 28, 0.65)",
                    "title": "#e6e6e6",
                    "group_bg": "rgba(30, 30, 35, 0.60)",
                    "group_border": "rgba(50, 50, 55, 0.5)",
                    "text": "#e6e6e6",
                    "desc": "#b0b0b0",
                    "btn_bg": "rgba(45, 45, 50, 0.50)",
                    "btn_border": "rgba(60, 60, 65, 0.40)",
                    "btn_text": "#b0b0b0",
                    "btn_checked_bg_start": "rgba(139, 92, 246, 0.70)",
                    "btn_checked_bg_end": "rgba(124, 58, 237, 0.70)",
                    "btn_checked_border": "rgba(139, 92, 246, 0.80)",
                    "btn_hover_bg": "rgba(55, 55, 60, 0.70)",
                    "btn_hover_border": "rgba(139, 92, 246, 0.40)",
                    "back_btn_bg": "rgba(30, 30, 35, 0.60)",
                    "back_btn_border": "rgba(50, 50, 55, 0.60)",
                    "back_btn_text": "#b0b0b0",
                    "apply_btn_start": "rgba(34, 197, 94, 0.70)",
                    "apply_btn_end": "rgba(22, 163, 74, 0.80)",
                    "apply_btn_border": "rgba(34, 197, 94, 0.80)",
                    
                    # Кнопка удаления всех чатов
                    "delete_all_btn_bg": "rgba(220, 85, 85, 0.15)",
                    "delete_all_btn_hover": "rgba(220, 85, 85, 0.25)",
                    "delete_all_btn_text": "#e89999",
                    "delete_all_btn_border": "rgba(220, 85, 85, 0.3)",
                    "delete_all_btn_disabled_bg": "rgba(60, 60, 65, 0.4)",
                    "delete_all_btn_disabled_border": "rgba(80, 80, 85, 0.4)",
                    "delete_all_btn_disabled_text": "rgba(120, 120, 125, 0.7)",
                    "preview_glass_container": "rgba(60, 75, 115, 0.72)",
                    "preview_glass_bg": "rgba(60, 60, 80, 0.80)",
                    "preview_glass_border": "rgba(120, 120, 180, 0.85)",
                    "preview_glass_text": "#e8e8ff",
                    "preview_matte_bg": "rgb(43, 43, 48)",
                    "preview_matte_border": "rgba(60, 60, 65, 0.95)",
                    "preview_matte_text": "#e0e0e0",
                    "preview_accent": "#9b7fe8",
                }
            else:
                # ТЁМНАЯ ТЕМА БЕЗ СТЕКЛА - матовый тёмный
                colors = {
                    "bg": "rgb(28, 28, 31)",
                    "title": "#f0f0f0",
                    "group_bg": "rgb(32, 32, 36)",
                    "group_border": "rgba(55, 55, 60, 0.9)",
                    "text": "#f0f0f0",
                    "desc": "#c0c0c0",
                    "btn_bg": "rgb(48, 48, 52)",
                    "btn_border": "rgb(68, 68, 72)",
                    "btn_text": "#c0c0c0",
                    "btn_checked_bg_start": "rgba(139, 92, 246, 1.0)",
                    "btn_checked_bg_end": "rgba(124, 58, 237, 1.0)",
                    "btn_checked_border": "rgba(139, 92, 246, 1.0)",
                    "btn_hover_bg": "rgb(58, 58, 62)",
                    "btn_hover_border": "rgba(139, 92, 246, 0.6)",
                    "back_btn_bg": "rgb(32, 32, 36)",
                    "back_btn_border": "rgba(55, 55, 60, 0.95)",
                    "back_btn_text": "#c0c0c0",
                    "apply_btn_start": "rgba(34, 197, 94, 1.0)",
                    "apply_btn_end": "rgba(22, 163, 74, 1.0)",
                    "apply_btn_border": "rgba(34, 197, 94, 1.0)",
                    
                    # Кнопка удаления всех чатов
                    "delete_all_btn_bg": "rgba(220, 85, 85, 0.15)",
                    "delete_all_btn_hover": "rgba(220, 85, 85, 0.25)",
                    "delete_all_btn_text": "#e89999",
                    "delete_all_btn_border": "rgba(220, 85, 85, 0.3)",
                    "delete_all_btn_disabled_bg": "rgba(60, 60, 65, 0.4)",
                    "delete_all_btn_disabled_border": "rgba(80, 80, 85, 0.4)",
                    "delete_all_btn_disabled_text": "rgba(120, 120, 125, 0.7)",
                    "preview_glass_container": "rgba(60, 75, 115, 0.72)",
                    "preview_glass_bg": "rgba(60, 60, 80, 0.80)",
                    "preview_glass_border": "rgba(120, 120, 180, 0.85)",
                    "preview_glass_text": "#e8e8ff",
                    "preview_matte_bg": "rgb(43, 43, 48)",
                    "preview_matte_border": "rgba(60, 60, 65, 0.95)",
                    "preview_matte_text": "#e0e0e0",
                    "preview_accent": "#9b7fe8",
                }
        else:
            # СВЕТЛАЯ ТЕМА
            if liquid_glass:
                # СВЕТЛАЯ ТЕМА + СТЕКЛО
                colors = {
                    "bg": "rgba(255, 255, 255, 0.55)",
                    "title": "#222222",
                    "group_bg": "rgba(255, 255, 255, 0.75)",
                    "group_border": "rgba(255, 255, 255, 0.85)",
                    "text": "#222222",
                    "desc": "#5a5a5a",
                    "btn_bg": "rgba(255, 255, 255, 0.65)",
                    "btn_border": "rgb(200, 210, 222)",
                    "btn_text": "#3a3a3a",
                    "btn_checked_bg_start": "rgba(102, 126, 234, 0.80)",
                    "btn_checked_bg_end": "rgba(118, 75, 162, 0.80)",
                    "btn_checked_border": "rgba(102, 126, 234, 0.90)",
                    "btn_hover_bg": "rgba(255, 255, 255, 0.85)",
                    "btn_hover_border": "rgba(102, 126, 234, 0.50)",
                    "back_btn_bg": "rgba(255, 255, 255, 0.75)",
                    "back_btn_border": "rgba(203, 213, 225, 0.75)",
                    "back_btn_text": "#3a3a3a",
                    "apply_btn_start": "rgba(34, 197, 94, 0.80)",
                    "apply_btn_end": "rgba(22, 163, 74, 0.90)",
                    "apply_btn_border": "rgba(34, 197, 94, 0.90)",
                    
                    # Кнопка удаления всех чатов
                    "delete_all_btn_bg": "rgba(220, 85, 85, 0.08)",
                    "delete_all_btn_hover": "rgba(220, 85, 85, 0.15)",
                    "delete_all_btn_text": "#c85555",
                    "delete_all_btn_border": "rgba(220, 85, 85, 0.2)",
                    "delete_all_btn_disabled_bg": "rgba(220, 220, 225, 0.5)",
                    "delete_all_btn_disabled_border": "rgba(200, 200, 205, 0.5)",
                    "delete_all_btn_disabled_text": "rgba(160, 160, 165, 0.8)",
                    "preview_glass_container": "rgba(110, 140, 185, 0.72)",
                    "preview_glass_bg": "rgba(200, 210, 240, 0.75)",
                    "preview_glass_border": "rgba(150, 170, 220, 0.90)",
                    "preview_glass_text": "#1a1a3a",
                    "preview_matte_bg": "rgb(242, 242, 245)",
                    "preview_matte_border": "rgba(200, 200, 205, 0.95)",
                    "preview_matte_text": "#1a1a1a",
                    "preview_accent": "#667eea",
                }
            else:
                # СВЕТЛАЯ ТЕМА БЕЗ СТЕКЛА - плоский
                colors = {
                    "bg": "rgb(246, 246, 248)",
                    "title": "#1a1a1a",
                    "group_bg": "rgb(252, 252, 254)",
                    "group_border": "rgba(210, 210, 215, 0.95)",
                    "text": "#1a1a1a",
                    "desc": "#4a4a4a",
                    "btn_bg": "rgb(242, 242, 245)",
                    "btn_border": "rgb(210, 210, 215)",
                    "btn_text": "#2a2a2a",
                    "btn_checked_bg_start": "rgba(102, 126, 234, 1.0)",
                    "btn_checked_bg_end": "rgba(118, 75, 162, 1.0)",
                    "btn_checked_border": "rgba(102, 126, 234, 1.0)",
                    "btn_hover_bg": "rgb(235, 235, 240)",
                    "btn_hover_border": "rgba(102, 126, 234, 0.7)",
                    "back_btn_bg": "rgb(246, 246, 248)",
                    "back_btn_border": "rgba(210, 210, 215, 0.95)",
                    "back_btn_text": "#2a2a2a",
                    "apply_btn_start": "rgba(34, 197, 94, 1.0)",
                    "apply_btn_end": "rgba(22, 163, 74, 1.0)",
                    "apply_btn_border": "rgba(34, 197, 94, 1.0)",
                    
                    # Кнопка удаления всех чатов
                    "delete_all_btn_bg": "rgba(220, 85, 85, 0.08)",
                    "delete_all_btn_hover": "rgba(220, 85, 85, 0.15)",
                    "delete_all_btn_text": "#c85555",
                    "delete_all_btn_border": "rgba(220, 85, 85, 0.2)",
                    "delete_all_btn_disabled_bg": "rgba(220, 220, 225, 0.5)",
                    "delete_all_btn_disabled_border": "rgba(200, 200, 205, 0.5)",
                    "delete_all_btn_disabled_text": "rgba(160, 160, 165, 0.8)",
                    "preview_glass_container": "rgba(110, 140, 185, 0.72)",
                    "preview_glass_bg": "rgba(200, 210, 240, 0.75)",
                    "preview_glass_border": "rgba(150, 170, 220, 0.90)",
                    "preview_glass_text": "#1a1a3a",
                    "preview_matte_bg": "rgb(242, 242, 245)",
                    "preview_matte_border": "rgba(200, 200, 205, 0.95)",
                    "preview_matte_text": "#1a1a1a",
                    "preview_accent": "#667eea",
                }
        
        style = f"""
            #settingsView {{
                background: {colors["bg"]};
            }}
            
            #settingsTitle {{
                color: {colors["title"]};
                font-size: 32px;
            }}
            
            #settingGroup {{
                background: {colors["group_bg"]};
                border: 1px solid {colors["group_border"]};
                border-radius: 18px;
                padding: 24px;
            }}
            
            #settingGroup QLabel {{
                color: {colors["text"]};
            }}
            
            #settingGroup QLabel[objectName="descLabel"] {{
                color: {colors["desc"]};
            }}
            
            #themeLightBtn, #themeDarkBtn,
            #glassOnBtn, #glassOffBtn {{
                background: {colors["btn_bg"]};
                border: 2px solid {colors["btn_border"]};
                border-radius: 12px;
                padding: 16px 22px;
                font-size: 15px;
                font-weight: 600;
                color: {colors["btn_text"]};
                min-height: 50px;
            }}
            
            #themeLightBtn:checked, #themeDarkBtn:checked,
            #glassOnBtn:checked, #glassOffBtn:checked {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors["btn_checked_bg_start"]},
                    stop:1 {colors["btn_checked_bg_end"]});
                border: 2px solid {colors["btn_checked_border"]};
                color: white;
            }}
            
            #themeLightBtn:hover, #themeDarkBtn:hover,
            #glassOnBtn:hover, #glassOffBtn:hover {{
                background: {colors["btn_hover_bg"]};
                border: 2px solid {colors["btn_hover_border"]};
            }}
            
            #themeLightBtn:checked:hover, #themeDarkBtn:checked:hover,
            #glassOnBtn:checked:hover, #glassOffBtn:checked:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors["btn_checked_bg_start"]},
                    stop:1 {colors["btn_checked_bg_end"]});
                border: 2px solid {colors["btn_checked_border"]};
                color: white;
            }}
            
            #settingsBackBtn {{
                background: {colors["back_btn_bg"]};
                border: 2px solid {colors["back_btn_border"]};
                border-radius: 14px;
                color: {colors["back_btn_text"]};
            }}
            
            #settingsBackBtn:hover {{
                background: {colors["btn_hover_bg"]};
                border: 2px solid {colors["btn_hover_border"]};
            }}
            
            #settingsApplyBtn {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {colors["apply_btn_start"]},
                    stop:1 {colors["apply_btn_end"]});
                border: 2px solid {colors["apply_btn_border"]};
                border-radius: 14px;
                color: white;
            }}
            
            #settingsApplyBtn:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(34, 197, 94, 0.95),
                    stop:1 rgba(22, 163, 74, 1.0));
            }}
            
            #deleteAllChatsBtn {{
                background: {colors["delete_all_btn_bg"]};
                border: 2px solid {colors["delete_all_btn_border"]};
                border-radius: 14px;
                color: {colors["delete_all_btn_text"]};
                font-weight: 600;
            }}
            
            #deleteAllChatsBtn:hover {{
                background: {colors["delete_all_btn_hover"]};
            }}
            
            #deleteAllChatsBtn:disabled {{
                background: {colors["delete_all_btn_disabled_bg"]};
                border: 2px solid {colors["delete_all_btn_disabled_border"]};
                color: {colors["delete_all_btn_disabled_text"]};
                font-weight: 400;
            }}
            
            #previewGlassBg {{
                background: {colors["preview_glass_container"]};
                border-radius: 16px;
            }}
            #previewGlassBubble {{
                background: {colors["preview_glass_bg"]};
                border: 1.5px solid {colors["preview_glass_border"]};
                border-radius: 24px;
            }}
            #previewGlassName {{ color: {colors["preview_accent"]}; background: transparent; }}
            #previewGlassText {{ color: {colors["preview_glass_text"]}; background: transparent; }}
            
            #previewMatteBg {{
                background: transparent;
                border-radius: 16px;
            }}
            #previewMatteBubble {{
                background: {colors["preview_matte_bg"]};
                border: 1.5px solid {colors["preview_matte_border"]};
                border-radius: 24px;
            }}
            #previewMatteName {{ color: {colors["preview_accent"]}; background: transparent; }}
            #previewMatteText {{ color: {colors["preview_matte_text"]}; background: transparent; }}
            
            #previewColLabel {{ color: {colors["desc"]}; background: transparent; }}
        """
        
        self.setStyleSheet(style)
        print(f"[SETTINGS_VIEW] ✓ Стили применены")






class MainWindow(AttachmentMixin, QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        global CURRENT_LANGUAGE
        self.current_language = CURRENT_LANGUAGE
        self.deep_thinking = False
        self.use_search = False
        self.is_generating = False
        self._regen_target_widget = None  # виджет-цель для add_regen_entry
        self.current_user_message = ""
        self.current_worker = None
        
        # ✅ ИСПРАВЛЕНИЕ: Список активных workers для предотвращения RuntimeError
        # WorkerSignals не должен удаляться пока worker работает
        self.active_workers = []  # Сильные ссылки на workers
        
        # Режим работы AI
        self.ai_mode = AI_MODE_FAST  # По умолчанию быстрый режим
        # Загружаем сохранённую модель из настроек
        self._load_model_preference()
        # При запуске: выгружаем все модели кроме выбранной (на случай грязного завершения),
        # затем загружаем в память только активную модель
        unload_all_models(except_key=llama_handler.CURRENT_AI_MODEL_KEY, synchronous=False)
        warm_up_model(llama_handler.CURRENT_AI_MODEL_KEY)
        
        # Таймер обдумывания
        self.thinking_start_time = None
        self.thinking_elapsed_time = 0
        
        # Режим редактирования
        self.is_editing = False
        self.editing_message_text = ""
        
        # Прикреплённые файлы (до 5 файлов одновременно)
        self.attached_files = []
        
        # ═══════════════════════════════════════════════════════════════
        # СИСТЕМА ХРАНЕНИЯ ФАЙЛОВ ОТКЛЮЧЕНА
        # ═══════════════════════════════════════════════════════════════
        # Файлы больше не копируются и не сохраняются
        # Используются только исходные пути для анализа AI
        print(f"[CHAT_FILES] ℹ️ Система хранения файлов отключена")
        
        
        # ═══════════════════════════════════════════════════════════════
        # DRAG-AND-DROP: Включаем поддержку перетаскивания файлов
        # ═══════════════════════════════════════════════════════════════
        self.setAcceptDrops(True)
        print("[DRAG-DROP] ✓ Поддержка перетаскивания файлов включена")
        
        
        # Менеджер чатов
        self.chat_manager = ChatManager()
        
        # Текущая тема и настройки интерфейса
        self.current_theme = "light"
        self.current_liquid_glass = True
        
        # ═══════════════════════════════════════════════════════════════
        # ЛОГИКА СТАРТОВОГО ЧАТА
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: Удаляем все старые ПУСТЫЕ чаты (без пользовательских сообщений)
        print("[STARTUP] Очистка старых пустых чатов...")
        self._cleanup_empty_chats_on_startup()
        
        # ШАГ 2: Создаём новый чат при запуске
        new_chat_id = self.chat_manager.create_chat("Новый чат")
        self.chat_manager.set_active_chat(new_chat_id)
        self.current_chat_id = new_chat_id
        # Уведомляем память DeepSeek о новом чате
        if _DS_MEMORY is not None:
            _DS_MEMORY.on_chat_switch(new_chat_id)
        
        # Помечаем этот чат как стартовый (пустой)
        self.startup_chat_id = new_chat_id
        self.startup_chat_has_messages = False
        print(f"[STARTUP] Создан новый стартовый чат ID={new_chat_id}")

        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 850)

        icon_pixmap = create_app_icon()
        self.setWindowIcon(QtGui.QIcon(icon_pixmap))

        # ── Animated background widget (lives behind everything) ──
        self.bg_widget = QtWidgets.QWidget()
        self.bg_widget.setObjectName("bgWidget")

        # Главный контейнер
        main_container = QtWidgets.QWidget()
        self.setCentralWidget(main_container)
        container_layout = QtWidgets.QHBoxLayout(main_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Боковая панель чатов
        self.sidebar = QtWidgets.QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(0)  # Изначально скрыта
        sidebar_layout = QtWidgets.QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 12, 0, 0)  # Верхний отступ как у title
        sidebar_layout.setSpacing(0)

        # Кнопка "Новый чат"
        new_chat_btn = NoFocusButton("+ Новый чат")
        new_chat_btn.setObjectName("newChatBtn")
        new_chat_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        new_chat_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        new_chat_btn.clicked.connect(self.create_new_chat)
        sidebar_layout.addWidget(new_chat_btn)

        # Список чатов
        self.chats_list = QtWidgets.QListWidget()
        self.chats_list.setObjectName("chatsList")
        self.chats_list.itemClicked.connect(self.switch_chat)
        self.chats_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.chats_list.customContextMenuRequested.connect(self.show_delete_panel)
        # Предотвращаем выход hover-фона за границы виджета
        self.chats_list.setViewportMargins(6, 8, 6, 8)  # отступы со всех сторон — hover не вылезает
        self.chats_list.viewport().setAutoFillBackground(False)
        self.chats_list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)  # убираем рамку QFrame
        sidebar_layout.addWidget(self.chats_list)

        # ═══════════════════════════════════════════════
        # НОВОЕ: Кнопка настроек (закреплена снизу sidebar)
        # ═══════════════════════════════════════════════
        self.settings_btn = NoFocusButton("⚙️ Настройки")
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.settings_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.settings_btn.clicked.connect(self.open_settings)
        sidebar_layout.addWidget(self.settings_btn)


        container_layout.addWidget(self.sidebar)

        # Панель удаления (справа от sidebar)
        self.delete_panel = QtWidgets.QWidget()
        self.delete_panel.setObjectName("deletePanel")
        self.delete_panel.setFixedWidth(0)  # Изначально скрыта
        delete_layout = QtWidgets.QVBoxLayout(self.delete_panel)
        delete_layout.setContentsMargins(0, 12, 0, 0)
        delete_layout.setSpacing(10)
        
        delete_layout.addStretch()
        
        # Кнопка удаления
        self.delete_chat_btn = QtWidgets.QPushButton("🗑️ Удалить чат")
        self.delete_chat_btn.setObjectName("deleteChatBtn")
        self.delete_chat_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.delete_chat_btn.clicked.connect(self.delete_selected_chat)
        delete_layout.addWidget(self.delete_chat_btn)
        
        delete_layout.addStretch()
        
        container_layout.addWidget(self.delete_panel)
        
        # ID чата для удаления
        self.chat_to_delete = None

        # Основная область
        central = QtWidgets.QWidget()
        central.setObjectName("central")
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title block
        title_widget = QtWidgets.QWidget()
        title_widget.setObjectName("titleWidget")
        self.title_widget = title_widget  # Сохраняем ссылку для blur эффекта
        title_layout = QtWidgets.QHBoxLayout(title_widget)
        title_layout.setContentsMargins(15, 12, 15, 12)
        title_layout.setSpacing(15)

        # Кнопка меню (иконка трёх полосок)
        self.menu_btn = NoFocusButton()
        self.menu_btn.setObjectName("menuBtn")
        self.menu_btn.setFixedSize(50, 50)
        self.menu_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.menu_btn.clicked.connect(self.toggle_sidebar)
        # Иконка будет установлена после применения темы
        title_layout.addWidget(self.menu_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        title_layout.addStretch()
        title_label = QtWidgets.QLabel(APP_TITLE)
        title_label.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        title_label.mousePressEvent = lambda event: self.show_model_info()
        title_label.setObjectName("titleLabel")
        font_title = _apple_font(22, weight=QtGui.QFont.Weight.Bold)
        title_label.setFont(font_title)
        title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(title_label, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)
        title_layout.addStretch()

        # Кастомная кнопка очистки с подсказкой
        class ClearButtonWithTooltip(QtWidgets.QPushButton):
            def __init__(self, text, parent=None):
                super().__init__(text, parent)
                self.glass_tooltip = None
            
            def enterEvent(self, event):
                # При наведении на неактивную кнопку показываем подсказку
                if not self.isEnabled():
                    if not self.glass_tooltip:
                        self.glass_tooltip = GlassTooltip("Нет сообщений для очистки")
                    # Показываем подсказку под кнопкой
                    button_center = self.rect().center()
                    global_pos = self.mapToGlobal(QtCore.QPoint(button_center.x(), self.height()))
                    self.glass_tooltip.show_at(global_pos)
                super().enterEvent(event)
            
            def leaveEvent(self, event):
                # Скрываем подсказку при уходе курсора
                if self.glass_tooltip:
                    self.glass_tooltip.hide()
                super().leaveEvent(event)
        
        self.clear_btn = ClearButtonWithTooltip("🗑️ Очистить")
        self.clear_btn.setObjectName("clearBtn")
        font_clear = _apple_font(13, weight=QtGui.QFont.Weight.Bold)
        self.clear_btn.setFont(font_clear)
        self.clear_btn.setFixedSize(120, 44)
        self.clear_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.clear_btn.clicked.connect(self.clear_chat)
        title_layout.addWidget(self.clear_btn, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        title_layout.addSpacing(8)

        main_layout.addWidget(title_widget)


        # ═══════════════════════════════════════════════════════════════
        # Chat display - QStackedWidget для переключения чат/настройки
        # ═══════════════════════════════════════════════════════════════
        self.content_stack = QtWidgets.QStackedWidget()
        self.content_stack.setObjectName("contentStack")
        
        # ✅ ИСПРАВЛЕНИЕ: Устанавливаем прозрачный фон для content_stack
        # Это предотвращает белое мигание при переключении страниц
        self.content_stack.setStyleSheet("QStackedWidget { background: transparent; }")

        # ═══════════════════════════════════════════════
        # PAGE 0: CHAT VIEW (существующий функционал)
        # ═══════════════════════════════════════════════
        chat_container = QtWidgets.QWidget()
        chat_container.setObjectName("chatContainer")
        chat_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        chat_layout = QtWidgets.QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("scrollArea")
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        self.scroll_area.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )

        self.scroll_area.setStyleSheet("background: transparent;")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")

        self.messages_widget = QtWidgets.QWidget()
        
        self.messages_layout = QtWidgets.QVBoxLayout()
        self.messages_layout.setContentsMargins(5, 5, 5, 20)
        self.messages_layout.setSpacing(8)
        self.messages_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        
        self.messages_widget.setLayout(self.messages_layout)
        
        self.messages_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum
        )

        self.messages_widget.setStyleSheet("background: transparent;")

        self.scroll_area.setWidget(self.messages_widget)
        
        # ═══════════════════════════════════════════════════════════════
        # УСТАНОВКА EVENT FILTER ДЛЯ БЛОКИРОВКИ SCROLL INPUT ВО ВРЕМЯ LAYOUT
        # ═══════════════════════════════════════════════════════════════
        # КРИТИЧНО: Устанавливаем фильтр событий на viewport, а не scroll_area.
        # EventFilter для обновления кнопки "вниз" после wheel событий
        self.scroll_area.viewport().installEventFilter(self)
        
        # EventFilter для обработки resize (обновление позиции кнопки)
        self.scroll_area.installEventFilter(self)
        
        print("[INIT] ✓ messages_layout выровнен вверх без stretch")
        print("[INIT] ✓ БЕЗ автоскролла - пользователь управляет прокруткой сам")
        print("[INIT] ✓ Event filter установлен для обновления кнопки после скролла")
        print("[INIT] ✓ Layout обновляется СИНХРОННО через adjustSize()")
        
        print("[ДИАГНОСТИКА] messages_widget.parent():", self.messages_widget.parent())
        print("[ДИАГНОСТИКА] scroll_area.viewport():", self.scroll_area.viewport())
        print("[ДИАГНОСТИКА] Совпадают?", self.messages_widget.parent() == self.scroll_area.viewport())
        
        # ═══════════════════════════════════════════════
        # НОВОЕ: FLOATING КНОПКА "ВНИЗ" (overlay)
        # ═══════════════════════════════════════════════
        # АРХИТЕКТУРА: Полностью пассивный overlay
        # - НЕ подключена к сигналам scrollbar (valueChanged, rangeChanged)
        # - НЕ вызывает update(), repaint(), updateGeometry()
        # - НЕ влияет на layout сообщений
        # - Обновляется ТОЛЬКО явно после завершения layout
        # - Обновляется после ручного скролла через eventFilter
        self.scroll_to_bottom_btn = ScrollToBottomButton(self.scroll_area)
        self.scroll_to_bottom_btn.clicked.connect(self.manual_scroll_to_bottom)
        
        # Позиционируем кнопку один раз при создании
        # Дальше позиция обновляется только при resize окна (см. eventFilter)
        self.scroll_to_bottom_btn.update_position(
            self.scroll_area.width(),
            self.scroll_area.height()
        )
        
        chat_layout.addWidget(self.scroll_area)
        
        # ═══════════════════════════════════════════════
        # PAGE 1: SETTINGS VIEW
        # ═══════════════════════════════════════════════
        self.settings_view = SettingsView()
        self.settings_view.close_requested.connect(self.close_settings)
        self.settings_view.settings_applied.connect(self.on_settings_applied)
        self.settings_view.delete_all_chats_requested.connect(self.confirm_delete_all_chats)
        
        # Добавляем страницы в stack
        self.content_stack.addWidget(chat_container)  # index 0
        self.content_stack.addWidget(self.settings_view)  # index 1
        
        # Показываем чат по умолчанию
        self.content_stack.setCurrentIndex(0)
        
        main_layout.addWidget(self.content_stack, stretch=1)

        # ═══════════════════════════════════════════════════════════════
        # ФАЙЛОВЫЕ ЧИПЫ — показываются над полем ввода когда файлы прикреплены
        # ═══════════════════════════════════════════════════════════════
        self.file_chip_container = QtWidgets.QWidget()
        self.file_chip_container.setObjectName("fileChipContainer")
        # ✅ ИСПРАВЛЕНИЕ: Устанавливаем максимальную высоту чтобы окно не увеличивалось
        self.file_chip_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Maximum  # Максимальный размер ограничен
        )
        self.file_chip_container.setMaximumHeight(120)  # Максимум ~2 ряда чипов
        self.file_chip_container.setStyleSheet("#fileChipContainer { background: transparent; border: none; }")
        self.file_chip_container.hide()  # Скрыт по умолчанию

        # Layout будет создан динамически в update_file_chips()
        main_layout.addWidget(self.file_chip_container)

        # Input elements - добавляем в main_layout ПОСЛЕ scroll area
        input_container = QtWidgets.QWidget()
        input_container.setObjectName("inputContainer")
        input_container.setStyleSheet("#inputContainer { background: transparent; border: none; }")
        # ✅ КРИТИЧНО: Fixed size policy для footer
        input_container.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,  # Изменено с Expanding на Preferred
            QtWidgets.QSizePolicy.Policy.Fixed
        )
        input_container.setFixedHeight(85)  # Фиксированная высота footer
        
        input_layout = QtWidgets.QHBoxLayout(input_container)
        input_layout.setContentsMargins(25, 15, 25, 10)
        input_layout.setSpacing(15)

        # Кнопка добавления файла
        self.attach_btn = NoFocusButton("+")
        self.attach_btn.setObjectName("attachBtn")
        font_attach = _apple_font(26, weight=QtGui.QFont.Weight.Bold)
        self.attach_btn.setFont(font_attach)
        self.attach_btn.setFixedSize(60, 60)
        self.attach_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.attach_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.attach_btn.clicked.connect(self.show_attach_menu)
        input_layout.addWidget(self.attach_btn)

        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setPlaceholderText("Введите сообщение...")
        self.input_field.setObjectName("inputField")
        font_input = _apple_font(14)
        self.input_field.setFont(font_input)
        self.input_field.setMinimumHeight(60)
        self.input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_field, stretch=1)
        
        # Кнопка выбора режима AI (новая)
        self.mode_btn = NoFocusButton(self.ai_mode)
        self.mode_btn.setObjectName("modeBtn")
        font_mode = _apple_font(12, weight=QtGui.QFont.Weight.Medium)
        self.mode_btn.setFont(font_mode)
        self.mode_btn.setFixedSize(95, 60)
        self.mode_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.mode_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.mode_btn.clicked.connect(self.show_mode_menu)
        input_layout.addWidget(self.mode_btn)

        self.send_btn = NoFocusButton("→")
        self.send_btn.setObjectName("sendBtn")
        font_btn = _apple_font(22, weight=QtGui.QFont.Weight.Bold)
        self.send_btn.setFont(font_btn)
        self.send_btn.setFixedSize(60, 60)
        self.send_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.send_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)

        # ✅ КРИТИЧНО: Добавляем input_container в main_layout с stretch=0
        main_layout.addWidget(input_container, 0)
        
        # Store reference
        self.input_container = input_container

        # Статус - fixed at bottom
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("statusLabel")
        font_status = _apple_font(11)
        self.status_label.setFont(font_status)
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.status_label.setContentsMargins(30, 0, 30, 10)
        # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: фиксированная высота предотвращает
        # пересчёт layout при смене текста (анимация точек "...")
        self.status_label.setFixedHeight(24)
        main_layout.addWidget(self.status_label)


        # Добавляем основную область в контейнер
        container_layout.addWidget(central)

        self.threadpool = QtCore.QThreadPool()

        # Устанавливаем фильтр событий для автозакрытия sidebar при клике по рабочей области
        self.messages_widget.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)
        chat_container.installEventFilter(self)

        # Загружаем сохранённые настройки
        saved_settings = self.load_saved_settings()
        theme = saved_settings.get("theme", "light")
        liquid_glass = saved_settings.get("liquid_glass", True)
        
        print(f"[INIT] Загружены настройки: тема={theme}, стекло={liquid_glass}")
        
        # КРИТИЧНО: Обновляем self.current_theme ДО применения стилей
        # Без этого меню + и режимов не знают какая тема активна
        self.current_theme = theme
        self.current_liquid_glass = liquid_glass
        
        # Применяем стили с загруженными настройками
        self.apply_styles(theme=theme, liquid_glass=liquid_glass)
        
        # Применяем тему к кнопке "вниз"
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.scroll_to_bottom_btn.apply_theme_styles(theme=theme, liquid_glass=liquid_glass)
        
        # Обновляем settings_view с правильной темой
        if hasattr(self, 'settings_view'):
            self.settings_view.current_settings["theme"] = theme
            self.settings_view.current_settings["liquid_glass"] = liquid_glass
            self.settings_view.pending_settings["theme"] = theme
            self.settings_view.pending_settings["liquid_glass"] = liquid_glass
            self.settings_view.apply_settings_styles()
        
        self.load_chats_list()
        self.load_current_chat()
        
        # Флаг первого показа для финализации layout
        self._first_show_done = False
    
    def load_saved_settings(self) -> dict:
        """Загрузить сохранённые настройки из файла"""
        try:
            if os.path.exists("app_settings.json"):
                with open("app_settings.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[SETTINGS] Ошибка загрузки настроек: {e}")
        
        # Возвращаем значения по умолчанию
        return {"theme": "light", "liquid_glass": True}
    
    def showEvent(self, event):
        """
        Обработчик первого показа окна.
        
        КРИТИЧНО: После первого показа окна выполняем финализацию layout.
        Это исправляет баг, когда layout не обновляется до первого скролла.
        """
        super().showEvent(event)
        
        if not self._first_show_done:
            self._first_show_done = True
            # Плавное появление всего окна при запуске
            self._start_window_fade_in()
            # Откладываем финализацию на следующий цикл event loop
            # Это гарантирует что все виджеты полностью отрендерены
            QtCore.QTimer.singleShot(0, self._finalize_initial_layout)

    def _start_window_fade_in(self):
        """
        Плавное появление всего окна при запуске.
        Использует setWindowOpacity — без патчей и QGraphicsEffect.
        """
        self.setWindowOpacity(0.0)
        
        self._fade_in_anim = QtCore.QPropertyAnimation(self, b"windowOpacity")
        self._fade_in_anim.setDuration(500)          # 500ms — мягко и быстро
        self._fade_in_anim.setStartValue(0.0)
        self._fade_in_anim.setEndValue(1.0)
        self._fade_in_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._fade_in_anim.start()
    
    def _finalize_initial_layout(self):
        """
        Финализация layout после первого показа окна.
        
        АЛГОРИТМ:
        1. Дождаться завершения layout через event loop (уже сделано через singleShot(0))
        2. Обновить только контейнер сообщений
        3. НЕ вызывать автоскролл
        4. НЕ использовать processEvents, updateGeometry, adjustSize
        """
        try:
            # Мягкое обновление контейнера сообщений
            if hasattr(self, 'messages_widget'):
                self.messages_widget.update()
            
            # Обновляем scroll area
            if hasattr(self, 'scroll_area'):
                self.scroll_area.update()
            
            print("[LAYOUT_FINALIZE] ✓ Layout финализирован после первого показа")
        except Exception as e:
            print(f"[LAYOUT_FINALIZE] ✗ Ошибка: {e}")
    
    def closeEvent(self, event):
        """
        Закрытие окна — мгновенное даже если ИИ генерирует ответ.
        Перед выходом синхронно выгружает все модели из памяти Ollama,
        чтобы при следующем запуске не было «призрачных» загруженных весов.
        os._exit(0) убивает процесс сразу после выгрузки.
        """
        import os as _os, threading as _thr

        print("[CLOSE] Закрытие приложения...")

        # 1. Флаг — воркеры не шлют сигналы
        llama_handler._APP_SHUTTING_DOWN = True

        # 2. Отменяем текущего воркера
        if hasattr(self, 'current_worker') and self.current_worker is not None:
            try:
                self.current_worker._cancelled = True
            except Exception:
                pass

        # 3. Скрываем окно сразу — UI не подвисает
        self.hide()
        event.accept()

        # 4. Синхронно выгружаем ВСЕ модели из памяти Ollama.
        #    Timeout 4с на каждую — суммарно не более ~12с для 3 моделей.
        #    Если Ollama недоступна — просто пропускаем, не блокируем выход.
        print("[CLOSE] Выгружаем все модели из памяти Ollama…")
        unload_all_models(except_key=None, synchronous=True, timeout=4)
        print("[CLOSE] ✓ Модели выгружены")

        # 5. Закрываем HTTP-сессию
        try:
            llama_handler._OLLAMA_SESSION.close()
        except Exception:
            pass

        # 6. Останавливаем Ollama, если мы её сами запускали
        try:
            from ollama_manager import stop_managed_ollama
            stop_managed_ollama()
        except Exception:
            pass

        # 7. os._exit(0) — убивает процесс немедленно
        print("[CLOSE] ✓ os._exit(0)")
        _os._exit(0)

    def resizeEvent(self, event):
        """
        Обработка изменения размера окна.
        
        КРИТИЧНО:
        - Обновляем ТОЛЬКО позицию overlay-кнопки "вниз"
        - Обновляем размер blur overlay если он существует
        - НЕ трогаем layout сообщений
        - НЕ вызываем updateGeometry или invalidate
        """
        super().resizeEvent(event)
        
        # Обновляем позицию overlay-кнопки при изменении размера scroll_area
        if hasattr(self, 'scroll_to_bottom_btn') and hasattr(self, 'scroll_area'):
            self.scroll_to_bottom_btn.update_position(
                self.scroll_area.width(),
                self.scroll_area.height()
            )
        
        # ✅ Обновляем размер blur overlay
        if hasattr(self, '_blur_overlay') and self._blur_overlay.isVisible():
            self._blur_overlay.setGeometry(self.rect())

        # ✅ Если меню не открыто — гарантируем что кнопка «+» видима
        # (защита от случая когда graphicsEffect остался с opacity=0 после ресайза)
        if not getattr(self, '_menu_is_open', False):
            if hasattr(self, 'attach_btn'):
                self.attach_btn.setGraphicsEffect(None)
    
    # position_input_elements() удалён - footer теперь в layout
    
    def apply_styles(self, theme: str = "light", liquid_glass: bool = True):
        """
        Применить стили с поддержкой тем и liquid glass.
        
        Параметры:
        - theme: "light" или "dark"
        - liquid_glass: True/False - включить/выключить стеклянные эффекты
        """
        
        print(f"[APPLY_STYLES] Применение стилей: theme={theme}, liquid_glass={liquid_glass}")
        
        # Обновляем иконку меню в зависимости от темы
        if hasattr(self, 'menu_btn'):
            menu_icon = create_menu_icon(theme=theme)
            self.menu_btn.setIcon(QtGui.QIcon(menu_icon))
            self.menu_btn.setIconSize(QtCore.QSize(50, 50))
        
        # ═══════════════════════════════════════════════════════════
        # ЦВЕТОВЫЕ ПАЛИТРЫ - 4 ВАРИАНТА
        # ═══════════════════════════════════════════════════════════
        
        if theme == "dark":
            if liquid_glass:
                # ТЁМНАЯ ТЕМА + СТЕКЛО - тёмное стекло, НЕ светлое
                colors = {
                    "main_bg": "#1e1e21",  # Тёмный фон
                    "central_bg": "rgba(30, 30, 35, 0.70)",  # Тёмное полупрозрачное стекло
                    "sidebar_bg": "rgba(24, 24, 28, 0.65)",  # Тёмное стекло для sidebar
                    
                    "central_border": "rgba(50, 50, 55, 0.4)",  # Мягкие тёмные границы
                    "sidebar_border": "rgba(50, 50, 55, 0.35)",
                    
                    "text_primary": "#e6e6e6",  # Светлый текст для читаемости
                    "text_secondary": "#b0b0b0",
                    "text_tertiary": "#808080",
                    
                    "btn_bg": "rgba(45, 45, 50, 0.55)",  # Тёмные полупрозрачные кнопки
                    "btn_bg_hover": "rgba(55, 55, 60, 0.65)",
                    "btn_border": "rgb(60, 60, 65)",
                    
                    "input_bg_start": "rgba(38, 38, 44, 0.58)",  # Тёмные инпуты
                    "input_bg_end": "rgba(38, 38, 44, 0.58)",
                    "input_btn_bg": "rgba(30, 30, 35, 0.70)",    # Фон кнопок — одинаковый с шапкой
                    "input_btn_bg_hover": "rgba(50, 50, 58, 0.80)",
                    "input_border": "rgb(55, 55, 62)",
                    "input_focus_border": "rgb(95, 62, 168)",
                    
                    "accent_primary": "rgba(139, 92, 246, 0.3)",  # Фиолетовый акцент
                    "accent_hover": "rgb(124, 77, 236)",
                    
                    "title_bg": "rgba(30, 30, 35, 0.70)",
                    "title_border": "rgb(50, 50, 55)",
                    
                    # Мягкая красная кнопка очистки для тёмной темы
                    "clear_btn_bg": "rgba(220, 85, 85, 0.15)",
                    "clear_btn_hover": "rgba(220, 85, 85, 0.25)",
                    "clear_btn_pressed": "rgba(220, 85, 85, 0.35)",
                    "clear_btn_text": "#e89999",
                    "clear_btn_text_hover": "#f0aaaa",
                    "clear_btn_border": "rgba(220, 85, 85, 0.3)",
                    "clear_btn_border_hover": "rgba(220, 85, 85, 0.45)",
                }
            else:
                # ТЁМНАЯ ТЕМА БЕЗ СТЕКЛА - матовый тёмный интерфейс
                colors = {
                    "main_bg": "#1e1e21",
                    "central_bg": "rgb(32, 32, 36)",  # НЕПРОЗРАЧНЫЙ тёмно-серый
                    "sidebar_bg": "rgb(28, 28, 31)",  # НЕПРОЗРАЧНЫЙ
                    
                    "central_border": "rgba(55, 55, 60, 0.9)",  # Чёткие границы
                    "sidebar_border": "rgba(55, 55, 60, 0.85)",
                    
                    "text_primary": "#f0f0f0",  # Очень светлый текст для контраста
                    "text_secondary": "#c0c0c0",
                    "text_tertiary": "#909090",
                    
                    "btn_bg": "rgb(48, 48, 52)",  # НЕПРОЗРАЧНЫЕ кнопки
                    "btn_bg_hover": "rgb(58, 58, 62)",
                    "btn_border": "rgb(68, 68, 72)",
                    
                    "input_bg_start": "rgba(42, 42, 46, 0.72)",
                    "input_bg_end": "rgba(42, 42, 46, 0.72)",
                    "input_btn_bg": "rgba(32, 32, 36, 0.90)",
                    "input_btn_bg_hover": "rgba(50, 50, 56, 0.95)",
                    "input_border": "rgb(58, 58, 62)",
                    "input_focus_border": "rgb(95, 62, 168)",
                    
                    "accent_primary": "rgba(139, 92, 246, 0.45)",
                    "accent_hover": "rgb(124, 77, 236)",
                    
                    "title_bg": "rgb(32, 32, 36)",
                    "title_border": "rgba(55, 55, 60, 0.9)",
                    
                    # Мягкая красная кнопка очистки для тёмной темы
                    "clear_btn_bg": "rgba(220, 85, 85, 0.15)",
                    "clear_btn_hover": "rgba(220, 85, 85, 0.25)",
                    "clear_btn_pressed": "rgba(220, 85, 85, 0.35)",
                    "clear_btn_text": "#e89999",
                    "clear_btn_text_hover": "#f0aaaa",
                    "clear_btn_border": "rgba(220, 85, 85, 0.3)",
                    "clear_btn_border_hover": "rgba(220, 85, 85, 0.45)",
                }
        else:
            # СВЕТЛАЯ ТЕМА
            if liquid_glass:
                # СВЕТЛАЯ ТЕМА + СТЕКЛО - классический Liquid Glass
                colors = {
                    "main_bg": "#a1a1aa",
                    "central_bg": "rgba(255, 255, 255, 0.55)",
                    "sidebar_bg": "rgba(255, 255, 255, 0.42)",
                    
                    "central_border": "rgba(255, 255, 255, 0.72)",
                    "sidebar_border": "rgba(255, 255, 255, 0.55)",
                    
                    "text_primary": "#222222",  # Тёмный текст для контраста
                    "text_secondary": "#3a3a3a",
                    "text_tertiary": "#5a5a5a",
                    
                    "btn_bg": "rgba(255, 255, 255, 0.60)",
                    "btn_bg_hover": "rgba(255, 255, 255, 0.78)",
                    "btn_border": "rgba(255, 255, 255, 0.70)",
                    
                    "input_bg_start": "rgba(248, 248, 250, 0.70)",
                    "input_bg_end": "rgba(242, 242, 245, 0.70)",
                    "input_btn_bg": "rgba(255, 255, 255, 0.55)",
                    "input_btn_bg_hover": "rgba(255, 255, 255, 0.72)",
                    "input_border": "rgb(210, 210, 220)",
                    "input_focus_border": "rgb(72, 94, 185)",
                    
                    "accent_primary": "rgba(102, 126, 234, 0.18)",
                    "accent_hover": "rgb(82, 106, 214)",
                    
                    "title_bg": "rgba(255, 255, 255, 0.55)",
                    "title_border": "rgb(210, 215, 225)",
                    
                    # Мягкая красная кнопка очистки для светлой темы
                    "clear_btn_bg": "rgba(220, 85, 85, 0.08)",
                    "clear_btn_hover": "rgba(220, 85, 85, 0.15)",
                    "clear_btn_pressed": "rgba(220, 85, 85, 0.22)",
                    "clear_btn_text": "#c85555",
                    "clear_btn_text_hover": "#b84444",
                    "clear_btn_border": "rgba(220, 85, 85, 0.2)",
                    "clear_btn_border_hover": "rgba(220, 85, 85, 0.35)",
                }
            else:
                # СВЕТЛАЯ ТЕМА БЕЗ СТЕКЛА - плоский iOS-like
                colors = {
                    "main_bg": "#d4d4d8",  # Светло-серый фон
                    "central_bg": "rgb(252, 252, 254)",  # НЕПРОЗРАЧНЫЙ белый
                    "sidebar_bg": "rgb(246, 246, 248)",  # НЕПРОЗРАЧНЫЙ светло-серый
                    
                    "central_border": "rgba(210, 210, 215, 0.95)",
                    "sidebar_border": "rgba(210, 210, 215, 0.9)",
                    
                    "text_primary": "#1a1a1a",  # Очень тёмный текст
                    "text_secondary": "#2a2a2a",
                    "text_tertiary": "#4a4a4a",
                    
                    "btn_bg": "rgb(242, 242, 245)",  # НЕПРОЗРАЧНЫЕ кнопки
                    "btn_bg_hover": "rgb(235, 235, 240)",
                    "btn_border": "rgb(210, 210, 215)",
                    
                    "input_bg_start": "rgba(248, 248, 250, 0.75)",
                    "input_bg_end": "rgba(242, 242, 245, 0.75)",
                    "input_btn_bg": "rgba(252, 252, 254, 0.90)",
                    "input_btn_bg_hover": "rgba(240, 240, 245, 0.95)",
                    "input_border": "rgb(210, 210, 215)",
                    "input_focus_border": "rgb(72, 94, 185)",
                    
                    "accent_primary": "rgba(102, 126, 234, 0.25)",
                    "accent_hover": "rgb(82, 106, 214)",
                    
                    "title_bg": "rgb(252, 252, 254)",
                    "title_border": "rgb(210, 210, 215)",
                    
                    # Мягкая красная кнопка очистки для светлой темы
                    "clear_btn_bg": "rgba(220, 85, 85, 0.08)",
                    "clear_btn_hover": "rgba(220, 85, 85, 0.15)",
                    "clear_btn_pressed": "rgba(220, 85, 85, 0.22)",
                    "clear_btn_text": "#c85555",
                    "clear_btn_text_hover": "#b84444",
                    "clear_btn_border": "rgba(220, 85, 85, 0.2)",
                    "clear_btn_border_hover": "rgba(220, 85, 85, 0.35)",
                }
        
        style = f"""
        /* ═══════════════════════════════════════════════
           GLOBAL — убираем focus ring у всех кнопок
           ═══════════════════════════════════════════════ */
        QPushButton {{
            outline: none;
        }}
        QPushButton:focus {{
            outline: none;
        }}
        QToolButton {{
            outline: none;
        }}
        QToolButton:focus {{
            outline: none;
        }}

        /* ═══════════════════════════════════════════════
           BASE — основной фон
           ═══════════════════════════════════════════════ */
        QMainWindow {{
            background: {colors["main_bg"]};
        }}

        /* ═══════════════════════════════════════════════
           CENTRAL PANEL — основная панель
           ═══════════════════════════════════════════════ */
        #central {{
            background: {colors["central_bg"]};
            border-radius: 0px;
        }}

        /* ═══════════════════════════════════════════════
           SIDEBAR — боковая панель
           ═══════════════════════════════════════════════ */
        #sidebar {{
            background: {colors["sidebar_bg"]};
            border-right: 1.5px solid {colors["sidebar_border"]};
            border-radius: 0px;
        }}

        /* ── New-chat button ── */
        #newChatBtn {{
            background: {colors["btn_bg"]};
            color: {colors["text_secondary"]};
            border: 1.5px solid {colors["btn_border"]};
            border-radius: 14px;
            padding: 18px 20px;
            margin: 12px 10px;
            font-size: 16px;
            font-weight: 700;
            text-align: left;
        }}
        #newChatBtn:hover {{
            background: {colors["btn_bg_hover"]};
            border: 1.5px solid {colors["accent_hover"]};
        }}

        /* ── Chat list ── */
        #chatsList {{
            background: transparent;
            border: none;
            outline: none;
            padding: 0px;
            border-radius: 12px;
        }}
        #chatsList::item {{
            padding: 12px 14px;
            margin: 2px 0px;
            border-radius: 10px;
            border: none;
            color: {colors["text_secondary"]};
            font-size: 14px;
            font-weight: 500;
            line-height: 1.4;
        }}
        #chatsList::item:hover {{
            background: {colors["btn_bg"]};
            border-left: 2px solid transparent;
        }}
        #chatsList::item:selected {{
            background: {colors["accent_primary"]};
            color: {colors["text_primary"]};
            font-weight: 600;
            border-left: 3px solid {colors["accent_hover"]};
        }}

        /* ── Settings button ── */
        #settingsBtn {{
            background: {colors["btn_bg"]};
            color: {colors["text_secondary"]};
            border: 1.5px solid {colors["btn_border"]};
            border-radius: 14px;
            padding: 18px 20px;
            margin: 12px 10px;
            font-size: 16px;
            font-weight: 700;
            text-align: left;
        }}
        #settingsBtn:hover {{
            background: {colors["btn_bg_hover"]};
            border: 1.5px solid {colors["accent_hover"]};
        }}


        /* ── Delete panel ── */
        #deletePanel {{
            background: {colors["sidebar_bg"]};
            border-left: 1px solid {colors["sidebar_border"]};
            padding: 15px;
        }}
        #deleteChatBtn {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(239, 68, 68, 0.75),
                stop:1 rgba(220, 38, 38, 0.85));
            color: white;
            border: none;
            border-radius: 12px;
            padding: 14px 20px;
            font-size: 14px;
            font-weight: 700;
        }}
        #deleteChatBtn:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(239, 68, 68, 0.90),
                stop:1 rgba(185, 28, 28, 0.95));
        }}
        #deleteChatBtn:pressed {{
            background: rgba(185, 28, 28, 0.95);
        }}

        /* ═══════════════════════════════════════════════
           TITLE BAR
           ═══════════════════════════════════════════════ */
        #menuBtn {{
            background: transparent;
            color: {colors["text_secondary"]};
            border: none;
            border-radius: 12px;
            padding: 0px;
            margin: 0px;
            min-width: 50px;
            max-width: 50px;
            min-height: 50px;
            max-height: 50px;
        }}
        #menuBtn:hover {{
            background: {colors["btn_bg"]};
            border-radius: 12px;
            margin: 6px;
        }}
        #menuBtn:pressed {{
            background: {colors["btn_bg_hover"]};
            border-radius: 12px;
            margin: 6px;
        }}

        #titleWidget {{
            background: {colors["title_bg"]};
            border: 1.5px solid {colors["title_border"]};
            border-radius: 18px;
            margin: 10px 15px;
            padding-top: 12px;
            padding-bottom: 12px;
        }}
        #titleLabel {{
            color: {colors["text_secondary"]};
            font-size: 22px;
            font-weight: 700;
            padding: 5px;
        }}

        #clearBtn {{
            background: {colors["clear_btn_bg"]};
            color: {colors["clear_btn_text"]};
            border: 1px solid {colors["clear_btn_border"]};
            border-radius: 12px;
            font-size: 12px;
            font-weight: 700;
            padding: 6px 10px;
            max-width: 105px;
            min-width: 95px;
        }}
        #clearBtn:hover {{
            background: {colors["clear_btn_hover"]};
            border: 1px solid {colors["clear_btn_border_hover"]};
            color: {colors["clear_btn_text_hover"]};
        }}
        #clearBtn:pressed {{
            background: {colors["clear_btn_pressed"]};
            color: {colors["clear_btn_text_hover"]};
        }}

        #settingsHeaderBtn {{
            background: transparent;
            border: none;
            border-radius: 12px;
            padding: 4px;
            font-size: 18px;
        }}
        #settingsHeaderBtn:hover {{
            background: {colors["clear_btn_hover"]};
            border: 1px solid {colors["clear_btn_border"]};
        }}
        #settingsHeaderBtn:pressed {{
            background: {colors["clear_btn_pressed"]};
        }}

        /* ═══════════════════════════════════════════════
           CHAT SCROLL AREA
           ═══════════════════════════════════════════════ */
        #chatContainer {{ background: transparent; }}

        QScrollArea            {{ background: transparent; border: none; }}
        QScrollArea > QWidget  {{ background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}

        QScrollBar:vertical {{
            background: transparent;
            width: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: transparent;
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: transparent;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{ height: 0px; }}

        /* ── Input field ── */
        #inputField {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_primary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            padding: 18px 25px;
            font-size: 16px;
        }}
        #inputField:focus {{
            border: 1.5px solid {colors["input_focus_border"]};
            background: {colors["input_btn_bg_hover"]};
        }}
        #inputField::placeholder {{
            color: {colors["text_tertiary"]};
        }}

        /* ── Attach button ── */
        #attachBtn {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 28px;
            font-weight: bold;
            text-align: center;
            padding: 0px;
            line-height: 60px;
            outline: none;
        }}
        #attachBtn:hover {{
            background: {colors["input_btn_bg_hover"]};
            border: 1.5px solid {colors["input_focus_border"]};
            outline: none;
        }}
        #attachBtn:focus {{
            outline: none;
            border: 1.5px solid {colors["input_border"]};
        }}
        #attachBtn:pressed {{
            background: {colors["accent_primary"]};
            border: 1.5px solid {colors["accent_hover"]};
            outline: none;
        }}

        /* ── Send button ── */
        #sendBtn {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 26px;
            outline: none;
        }}
        #sendBtn:hover {{
            background: {colors["input_btn_bg_hover"]};
            border: 1.5px solid {colors["input_focus_border"]};
            outline: none;
        }}
        #sendBtn:focus {{
            outline: none;
            border: 1.5px solid {colors["input_border"]};
        }}
        #sendBtn:pressed {{
            background: {colors["accent_primary"]};
            border: 1.5px solid {colors["accent_hover"]};
            outline: none;
        }}
        #sendBtn:disabled {{
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            outline: none;
        }}
        
        /* ── Mode button ── */
        #modeBtn {{
            background: {colors["input_btn_bg"]};
            color: {colors["text_tertiary"]};
            border: 1.5px solid {colors["input_border"]};
            border-radius: 30px;
            font-size: 12px;
            font-weight: 600;
            text-align: center;
            padding: 0px 10px;
            outline: none;
        }}
        #modeBtn:hover {{
            background: {colors["input_btn_bg_hover"]};
            border: 1.5px solid {colors["input_focus_border"]};
        }}
        #modeBtn:pressed {{
            background: {colors["accent_primary"]};
            border: 1.5px solid {colors["accent_hover"]};
        }}
        #modeBtn:focus {{
            outline: none;
            border: 1.5px solid {colors["input_border"]};
        }}

        /* ── Status label ── */
        #statusLabel {{
            color: {colors["text_tertiary"]};
            padding-left: 5px;
            font-style: italic;
        }}

        """
        self.setStyleSheet(style)

        try:
            self.scroll_area.viewport().setStyleSheet("background: transparent;")
            self.messages_widget.setStyleSheet("background: transparent;")
        except Exception:
            pass
        
        # ═══════════════════════════════════════════════════════════════════════
        # ОБНОВЛЕНИЕ СТИЛЕЙ СУЩЕСТВУЮЩИХ ВИДЖЕТОВ СООБЩЕНИЙ
        # ═══════════════════════════════════════════════════════════════════════
        # Когда пользователь переключает тему или liquid_glass,
        # нужно обновить стили всех существующих MessageWidget
        try:
            updated_count = 0
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    # Проверяем что это MessageWidget (у него есть метод update_message_styles)
                    if hasattr(widget, 'update_message_styles'):
                        widget.update_message_styles(theme, liquid_glass)
                        updated_count += 1
            
            if updated_count > 0:
                print(f"[APPLY_STYLES] ✓ Обновлено {updated_count} виджетов сообщений")
        except Exception as e:
            print(f"[APPLY_STYLES] ✗ Ошибка обновления виджетов: {e}")
        
        print(f"[APPLY_STYLES] ✓ Стили применены успешно: theme={theme}, liquid_glass={liquid_glass}")

        # Сбрасываем зависший QGraphicsOpacityEffect на кнопке режима
        if hasattr(self, 'mode_btn'):
            self.mode_btn.setGraphicsEffect(None)

    
    def show_model_info(self):
        """Показать информацию о модели при клике на заголовок"""
        current = get_current_display_name()
        QtWidgets.QMessageBox.information(
            self,
            "Информация о модели",
            f"{current} — локальная модель\n\nРаботает полностью офлайн на вашем компьютере.",
            QtWidgets.QMessageBox.StandardButton.Ok
        )

    def _check_first_launch(self):
        """
        Проверяет первый запуск: если LLaMA 3 не установлена — предлагает скачать.
        Флаг first_launch_done сохраняется ТОЛЬКО после того как пользователь
        согласился. Если нажал «Нет» — при следующем запуске снова предложит.
        """
        # Ollama не запущена — проверять модели бессмысленно, диалог не показываем
        from ollama_manager import is_ollama_running as _oll_running
        if not _oll_running():
            print("[FIRST_LAUNCH] ⏭ Ollama API не отвечает — пропускаем проверку моделей")
            return

        try:
            s = load_settings()
            if s.get("first_launch_done", False):
                # Флаг стоит, но модели нет — сбрасываем
                if not check_model_in_ollama("llama3"):
                    print("[FIRST_LAUNCH] Флаг стоит, но LLaMA 3 не установлена — предлагаем снова.")
                    save_settings({"first_launch_done": False})
                else:
                    print("[FIRST_LAUNCH] ✅ LLaMA 3 установлена, всё хорошо.")
                    return
        except Exception as e:
            log_error("FIRST_LAUNCH_READ", e)

        print("[FIRST_LAUNCH] Первый запуск — проверяем наличие LLaMA 3...")

        if check_model_in_ollama("llama3"):
            print("[FIRST_LAUNCH] ✅ LLaMA 3 уже установлена.")
            self._save_first_launch_flag()
            return

        print("[FIRST_LAUNCH] ⚠️ LLaMA 3 не найдена — показываем диалог скачивания.")

        reply = QtWidgets.QMessageBox.question(
            self,
            "LLaMA 3 не найдена",
            "⚠️ LLaMA 3 не скачана.\n\nЭто основная модель ассистента (~4.7 GB).\nХотите скачать её сейчас?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            dl_dialog = LlamaDownloadDialog(self)
            dl_dialog.exec()
            self._save_first_launch_flag()

    def _save_first_launch_flag(self):
        """Сохраняет флаг first_launch_done = True."""
        save_settings({"first_launch_done": True})
        print("[FIRST_LAUNCH] ✅ Флаг first_launch_done сохранён")

    def _load_model_preference(self):
        """Загружает сохранённую модель из файла настроек."""
        try:
            s = load_settings()
            saved_key = s.get("ai_model_key", "llama3")
            if saved_key in SUPPORTED_MODELS:
                llama_handler.CURRENT_AI_MODEL_KEY = saved_key
                llama_handler.ASSISTANT_NAME = get_current_display_name()
                print(f"[MODEL] Загружена модель из настроек: {llama_handler.ASSISTANT_NAME}")
            else:
                print(f"[MODEL] Неизвестная модель в настройках '{saved_key}' → llama3")
                llama_handler.CURRENT_AI_MODEL_KEY = "llama3"
        except Exception as e:
            log_error("LOAD_MODEL_PREF", e)

    def _save_model_preference(self):
        """Сохраняет выбранную модель в файл настроек."""
        save_settings({"ai_model_key": llama_handler.CURRENT_AI_MODEL_KEY})

    def change_ai_model(self, model_key: str):
        """
        Переключает активную модель.
        Выгружает ВСЕ остальные модели из памяти Ollama (keep_alive=0),
        затем загружает только выбранную.
        """
        if model_key not in SUPPORTED_MODELS:
            print(f"[MODEL] Неизвестная модель: {model_key}")
            return
        if llama_handler.CURRENT_AI_MODEL_KEY == model_key:
            return

        print(f"[MODEL] Смена модели: {llama_handler.CURRENT_AI_MODEL_KEY} → {model_key}")

        # Выгружаем ВСЕ модели кроме новой — на случай, если в памяти
        # что-то осталось от предыдущих сессий или переключений
        unload_all_models(except_key=model_key, synchronous=False)

        llama_handler.CURRENT_AI_MODEL_KEY = model_key
        llama_handler.ASSISTANT_NAME = get_current_display_name()
        self._save_model_preference()
        display = get_current_display_name()
        print(f"[MODEL] ✓ Активная модель: {display} ({get_current_ollama_model()})")
        # Загружаем только новую модель
        warm_up_model(model_key)

    def show_model_selector(self):
        """
        Переработанное меню выбора модели ИИ.
        Полностью адаптируется под тему (dark/light) и liquid_glass.
        Плавное появление (fade + scale) и закрытие.
        """
        is_dark        = self.current_theme == "dark"
        is_glass       = getattr(self, "current_liquid_glass", True)

        # ═══════════════════════════════════════════════════════════════
        # ПАЛИТРА — адаптируется под все 4 комбинации тема × стекло
        # ═══════════════════════════════════════════════════════════════
        if is_dark and is_glass:
            bg_overlay      = "rgba(0, 0, 0, 0.55)"            # затемнение за окном
            bg_card         = "rgba(28, 28, 38, 0.82)"
            card_border     = "rgba(90, 90, 130, 0.55)"
            title_col       = "#e8e8f8"
            sub_col         = "rgba(160, 160, 195, 0.75)"
            sep_col         = "rgba(80, 80, 115, 0.35)"
            row_bg          = "rgba(45, 45, 65, 0.70)"
            row_hover       = "rgba(60, 60, 88, 0.85)"
            row_border      = "rgba(70, 70, 105, 0.55)"
            badge_installed = "rgba(50, 200, 120, 0.18)"
            badge_border    = "rgba(50, 200, 120, 0.40)"
            badge_text      = "#52c87a"
            badge_miss_bg   = "rgba(200, 100, 60, 0.15)"
            badge_miss_bdr  = "rgba(200, 100, 60, 0.35)"
            badge_miss_txt  = "#e07a50"
            close_col       = "rgba(140, 140, 180, 0.65)"
            close_hover     = "#c0c0e0"
        elif is_dark and not is_glass:
            bg_overlay      = "rgba(0, 0, 0, 0.60)"
            bg_card         = "rgb(26, 26, 34)"
            card_border     = "rgba(65, 65, 90, 0.90)"
            title_col       = "#e2e2f2"
            sub_col         = "#8888aa"
            sep_col         = "rgba(65, 65, 90, 0.55)"
            row_bg          = "rgb(36, 36, 48)"
            row_hover       = "rgb(48, 48, 64)"
            row_border      = "rgba(62, 62, 88, 0.90)"
            badge_installed = "rgba(50, 200, 120, 0.18)"
            badge_border    = "rgba(50, 200, 120, 0.40)"
            badge_text      = "#52c87a"
            badge_miss_bg   = "rgba(200, 100, 60, 0.15)"
            badge_miss_bdr  = "rgba(200, 100, 60, 0.35)"
            badge_miss_txt  = "#e07a50"
            close_col       = "#66668a"
            close_hover     = "#aaaacc"
        elif not is_dark and is_glass:
            bg_overlay      = "rgba(30, 30, 60, 0.25)"
            bg_card         = "rgba(255, 255, 255, 0.72)"
            card_border     = "rgba(255, 255, 255, 0.85)"
            title_col       = "#1a1a3a"
            sub_col         = "rgba(80, 90, 140, 0.70)"
            sep_col         = "rgba(180, 185, 220, 0.40)"
            row_bg          = "rgba(255, 255, 255, 0.55)"
            row_hover       = "rgba(240, 242, 255, 0.90)"
            row_border      = "rgba(200, 205, 235, 0.65)"
            badge_installed = "rgba(30, 180, 100, 0.12)"
            badge_border    = "rgba(30, 180, 100, 0.35)"
            badge_text      = "#1aaa60"
            badge_miss_bg   = "rgba(200, 80, 40, 0.10)"
            badge_miss_bdr  = "rgba(200, 80, 40, 0.30)"
            badge_miss_txt  = "#cc5530"
            close_col       = "rgba(100, 110, 170, 0.60)"
            close_hover     = "#3a3a7a"
        else:  # light + matte
            bg_overlay      = "rgba(30, 30, 60, 0.30)"
            bg_card         = "rgb(248, 248, 252)"
            card_border     = "rgba(200, 205, 230, 0.95)"
            title_col       = "#1a1a3a"
            sub_col         = "#7788aa"
            sep_col         = "rgba(195, 200, 225, 0.70)"
            row_bg          = "rgb(240, 241, 250)"
            row_hover       = "rgb(228, 230, 248)"
            row_border      = "rgba(200, 205, 232, 0.95)"
            badge_installed = "rgba(30, 180, 100, 0.12)"
            badge_border    = "rgba(30, 180, 100, 0.35)"
            badge_text      = "#1aaa60"
            badge_miss_bg   = "rgba(200, 80, 40, 0.10)"
            badge_miss_bdr  = "rgba(200, 80, 40, 0.30)"
            badge_miss_txt  = "#cc5530"
            close_col       = "#8899bb"
            close_hover     = "#2a2a5a"

        active_grad = "qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #667eea,stop:1 #764ba2)"

        # ═══════════════════════════════════════════════════════════════
        # ДИАЛОГ — полупрозрачный оверлей поверх главного окна
        # ═══════════════════════════════════════════════════════════════
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Выбор модели ИИ")
        dialog.setWindowFlags(
            QtCore.Qt.WindowType.Dialog |
            QtCore.Qt.WindowType.FramelessWindowHint
        )
        if not IS_WINDOWS:
            dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)

        # Диалог покрывает всё главное окно (backdrop overlay)
        geo = self.geometry()
        dialog.setFixedSize(geo.width(), geo.height())
        dialog.move(geo.x(), geo.y())

        # Корневой layout — центрирует карточку по всему оверлею
        root_layout = QtWidgets.QVBoxLayout(dialog)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Затемнённый фон (клик по нему закрывает меню)
        dialog.setStyleSheet(f"background: {bg_overlay};")

        # ── КАРТОЧКА ────────────────────────────────────────────────
        card = QtWidgets.QFrame()
        card.setFixedWidth(430)
        card.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Minimum
        )
        card.setStyleSheet(f"""
            QFrame#modelCard {{
                background: {bg_card};
                border: 1px solid {card_border};
                border-radius: 24px;
            }}
        """)
        card.setObjectName("modelCard")
        root_layout.addWidget(card)

        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(22, 20, 22, 18)
        cl.setSpacing(0)

        # ── Шапка с иконкой и крестиком ─────────────────────────────
        header_row = QtWidgets.QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)

        # Иконка слева (декоративная)
        header_icon = QtWidgets.QLabel("🤖")
        header_icon.setStyleSheet(
            ("background: transparent; border: none; font-family: 'Segoe UI Emoji', 'Apple Color Emoji', sans-serif; font-size: 20px;" if IS_WINDOWS else "background: transparent; border: none; font-size: 20px;")
        )
        header_row.addWidget(header_icon)
        header_row.addStretch()

        # Кнопка закрытия ×
        x_btn = QtWidgets.QPushButton("×")
        x_btn.setFixedSize(28, 28)
        x_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        x_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        x_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {close_col};
                font-size: 20px;
                font-weight: 300;
                padding: 0px;
            }}
            QPushButton:hover {{
                color: {close_hover};
            }}
        """)
        header_row.addWidget(x_btn)
        cl.addLayout(header_row)

        cl.addSpacing(4)

        # ── Заголовок ────────────────────────────────────────────────
        title_lbl = QtWidgets.QLabel("Выбор модели ИИ")
        title_lbl.setStyleSheet(
            f"color: {title_col}; font-size: 19px; font-weight: 700; "
            f"background: transparent; border: none; letter-spacing: -0.3px;"
        )
        cl.addWidget(title_lbl)

        cl.addSpacing(4)

        hint_lbl = QtWidgets.QLabel("Все модели работают локально · без интернета")
        hint_lbl.setStyleSheet(
            f"color: {sub_col}; font-size: 12px; background: transparent; border: none;"
        )
        cl.addWidget(hint_lbl)

        cl.addSpacing(16)

        # ── Разделитель ──────────────────────────────────────────────
        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {sep_col}; border: none;")
        cl.addWidget(sep)

        cl.addSpacing(12)

        # ── Функция создания карточки модели ─────────────────────────
        def make_model_card(
            model_logo_key: str, name: str, desc: str,
            tag: str, is_active: bool, is_installed: bool
        ) -> QtWidgets.QPushButton:
            btn = QtWidgets.QPushButton()
            btn.setFixedHeight(74)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

            if is_active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {active_grad};
                        border: none;
                        border-radius: 16px;
                        padding: 0px;
                    }}
                    QPushButton:hover {{
                        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                            stop:0 #7b8ff5,stop:1 #8860b8);
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {row_bg};
                        border: 1px solid {row_border};
                        border-radius: 16px;
                        padding: 0px;
                    }}
                    QPushButton:hover {{
                        background: {row_hover};
                        border: 1px solid rgba(102, 126, 234, 0.50);
                    }}
                """)

            hl = QtWidgets.QHBoxLayout(btn)
            hl.setContentsMargins(16, 0, 16, 0)
            hl.setSpacing(14)

            # ── Иконка модели: PNG-логотип в скруглённом контейнере ───────
            icon_frame = QtWidgets.QWidget()
            icon_frame.setFixedSize(42, 42)
            icon_frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            if is_active:
                icon_frame.setStyleSheet(
                    "background: rgba(255,255,255,0.18); border-radius: 12px; border: none;"
                )
            else:
                if is_dark:
                    icon_frame.setStyleSheet(
                        "background: rgba(255,255,255,0.07); border-radius: 12px; border: none;"
                    )
                else:
                    icon_frame.setStyleSheet(
                        "background: rgba(102,126,234,0.10); border-radius: 12px; border: none;"
                    )

            icon_inner = QtWidgets.QVBoxLayout(icon_frame)
            icon_inner.setContentsMargins(5, 5, 5, 5)
            icon_inner.setSpacing(0)

            icon_lbl = QtWidgets.QLabel()
            icon_lbl.setFixedSize(32, 32)
            icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            icon_lbl.setStyleSheet("background: transparent; border: none;")

            # Загружаем логотип модели (сначала файл, потом base64)
            _px = _get_model_logo_pixmap(model_logo_key, size=30)
            if not _px.isNull():
                icon_lbl.setPixmap(_px)
            else:
                # Fallback: первая буква модели
                icon_lbl.setText(name[0].upper())
                icon_lbl.setStyleSheet(
                    f"background: transparent; border: none; "
                    f"font-size: 18px; font-weight: 700; "
                    f"color: {'#ffffff' if is_active else title_col};"
                )

            icon_inner.addWidget(icon_lbl, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
            hl.addWidget(icon_frame)

            # Текстовый блок
            vl = QtWidgets.QVBoxLayout()
            vl.setSpacing(3)
            vl.setContentsMargins(0, 0, 0, 0)

            name_col   = "#ffffff" if is_active else title_col
            desc_col   = "rgba(255,255,255,0.68)" if is_active else sub_col

            name_lbl = QtWidgets.QLabel(name)
            name_lbl.setStyleSheet(
                f"color: {name_col}; font-size: 15px; font-weight: 700; "
                f"background: transparent; border: none;"
            )
            name_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            vl.addWidget(name_lbl)

            desc_lbl = QtWidgets.QLabel(desc)
            desc_lbl.setStyleSheet(
                f"color: {desc_col}; font-size: 11px; "
                f"background: transparent; border: none;"
            )
            desc_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            vl.addWidget(desc_lbl)

            hl.addLayout(vl)
            hl.addStretch()

            # Правая зона: бейдж статуса + чекмарк
            right_vl = QtWidgets.QVBoxLayout()
            right_vl.setSpacing(4)
            right_vl.setContentsMargins(0, 0, 0, 0)
            right_vl.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight)

            # Бейдж «Установлена» / «Не скачана»
            badge = QtWidgets.QLabel("✓ Установлена" if is_installed else "↓ Не скачана")
            if is_active:
                badge.setStyleSheet(
                    "background: rgba(255,255,255,0.20); border-radius: 6px; "
                    "color: rgba(255,255,255,0.85); font-size: 10px; font-weight: 600; "
                    "padding: 2px 7px; border: none;"
                )
            elif is_installed:
                badge.setStyleSheet(
                    f"background: {badge_installed}; border: 1px solid {badge_border}; "
                    f"border-radius: 6px; color: {badge_text}; "
                    f"font-size: 10px; font-weight: 600; padding: 2px 7px;"
                )
            else:
                badge.setStyleSheet(
                    f"background: {badge_miss_bg}; border: 1px solid {badge_miss_bdr}; "
                    f"border-radius: 6px; color: {badge_miss_txt}; "
                    f"font-size: 10px; font-weight: 600; padding: 2px 7px;"
                )
            badge.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            right_vl.addWidget(badge, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

            # Чекмарк активной модели
            if is_active:
                check = QtWidgets.QLabel("●")
                check.setStyleSheet(
                    "color: rgba(255,255,255,0.90); font-size: 10px; "
                    "background: transparent; border: none;"
                )
                check.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                right_vl.addWidget(check, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

            hl.addLayout(right_vl)
            return btn

        # Проверяем установленность
        llama_installed    = check_model_in_ollama("llama3")
        deepseek_installed = check_model_in_ollama(DEEPSEEK_MODEL_NAME)
        mistral_installed  = check_model_in_ollama(MISTRAL_MODEL_NAME)

        # ── Кнопка удаления модели ───────────────────────────────────
        def _make_delete_btn(model_key, model_name, ollama_name, is_installed):
            """Красная кнопка 🗑 — видна только если модель установлена."""
            if not is_installed:
                # Невидимый спейсер нужного размера
                ph = QtWidgets.QWidget()
                ph.setFixedSize(36, 74)
                ph.setStyleSheet("background: transparent;")
                return ph

            btn = QtWidgets.QPushButton("🗑")
            btn.setFixedSize(36, 36)
            btn.setToolTip(f"Удалить {model_name} с диска")
            btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            if is_dark:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(200,60,60,0.12);
                        border: 1px solid rgba(200,70,70,0.30);
                        border-radius: 9px; font-size: 15px;
                        color: rgba(220,90,90,0.70);
                    }
                    QPushButton:hover {
                        background: rgba(200,55,55,0.28);
                        border: 1px solid rgba(220,80,80,0.65);
                        color: #ee5555;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(200,60,60,0.07);
                        border: 1px solid rgba(200,70,70,0.25);
                        border-radius: 9px; font-size: 15px;
                        color: rgba(190,60,60,0.65);
                    }
                    QPushButton:hover {
                        background: rgba(200,55,55,0.18);
                        border: 1px solid rgba(200,60,60,0.55);
                        color: #cc2222;
                    }
                """)

            def _on_delete_clicked():
                reply = QtWidgets.QMessageBox.question(
                    dialog,
                    f"Удалить {model_name}?",
                    f"⚠️ Вы уверены, что хотите удалить {model_name} с диска?\n\n"
                    f"Это освободит ~{('4.7' if model_key == 'llama3' else ('4.1' if model_key == 'deepseek' else '7.1'))} GB, "
                    f"но потом придётся скачивать заново.",
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No
                )
                if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                    dialog.accept()
                    self._delete_model(model_key, model_name, ollama_name)

            btn.clicked.connect(_on_delete_clicked)

            # Обёртка для выравнивания по центру строки 74px
            wrap = QtWidgets.QWidget()
            wrap.setFixedSize(40, 74)
            wrap.setStyleSheet("background: transparent;")
            wl = QtWidgets.QVBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignHCenter)
            wl.addWidget(btn)
            return wrap

        # ── Карточки моделей с кнопками удаления ───────────────────
        llama_btn = make_model_card(
            "llama3", "LLaMA 3",
            "Универсальная · быстрая · поддержка поиска",
            "8B", llama_handler.CURRENT_AI_MODEL_KEY == "llama3", llama_installed
        )
        llama_row = QtWidgets.QHBoxLayout()
        llama_row.setContentsMargins(0, 0, 0, 0)
        llama_row.setSpacing(6)
        llama_row.addWidget(llama_btn)
        llama_row.addWidget(_make_delete_btn("llama3", "LLaMA 3", "llama3", llama_installed))
        cl.addLayout(llama_row)
        cl.addSpacing(10)

        deepseek_btn = make_model_card(
            "deepseek", "DeepSeek",
            "Аналитика · математика · код",
            "7B", llama_handler.CURRENT_AI_MODEL_KEY == "deepseek", deepseek_installed
        )
        deepseek_row = QtWidgets.QHBoxLayout()
        deepseek_row.setContentsMargins(0, 0, 0, 0)
        deepseek_row.setSpacing(6)
        deepseek_row.addWidget(deepseek_btn)
        deepseek_row.addWidget(_make_delete_btn("deepseek", "DeepSeek", DEEPSEEK_MODEL_NAME, deepseek_installed))
        cl.addLayout(deepseek_row)
        cl.addSpacing(10)

        mistral_btn = make_model_card(
            "mistral", "Mistral Nemo",
            "Многоязычный · гибкий · 12B параметров",
            "12B", llama_handler.CURRENT_AI_MODEL_KEY == "mistral", mistral_installed
        )
        mistral_row = QtWidgets.QHBoxLayout()
        mistral_row.setContentsMargins(0, 0, 0, 0)
        mistral_row.setSpacing(6)
        mistral_row.addWidget(mistral_btn)
        mistral_row.addWidget(_make_delete_btn("mistral", "Mistral Nemo", MISTRAL_MODEL_NAME, mistral_installed))
        cl.addLayout(mistral_row)

        cl.addSpacing(16)

        # ── Нижний разделитель ───────────────────────────────────────
        sep2 = QtWidgets.QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {sep_col}; border: none;")
        cl.addWidget(sep2)

        cl.addSpacing(12)

        # ── Кнопка «Закрыть» ─────────────────────────────────────────
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.setFixedHeight(36)
        close_btn.setMinimumWidth(110)
        close_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        close_btn.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {close_col};
                border: 1px solid {sep_col};
                border-radius: 10px;
                font-size: 13px;
                font-weight: 500;
                padding: 0 18px;
            }}
            QPushButton:hover {{
                color: {close_hover};
                border: 1px solid rgba(102, 126, 234, 0.40);
                background: rgba(102, 126, 234, 0.07);
            }}
        """)
        cl.addWidget(close_btn, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # ═══════════════════════════════════════════════════════════════
        # АНИМАЦИЯ ПОЯВЛЕНИЯ: fade + slide-up карточки
        # ═══════════════════════════════════════════════════════════════
        dialog.setWindowOpacity(0.0)
        dialog.show()

        # Slide-up карточки через QGraphicsOpacityEffect + смещение
        card_effect = QtWidgets.QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(card_effect)
        card_effect.setOpacity(0.0)

        # Анимация прозрачности оверлея
        _fade_overlay = QtCore.QPropertyAnimation(dialog, b"windowOpacity")
        _fade_overlay.setDuration(220)
        _fade_overlay.setStartValue(0.0)
        _fade_overlay.setEndValue(1.0)
        _fade_overlay.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        # Анимация появления карточки
        _fade_card = QtCore.QPropertyAnimation(card_effect, b"opacity")
        _fade_card.setDuration(260)
        _fade_card.setStartValue(0.0)
        _fade_card.setEndValue(1.0)
        _fade_card.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        _anim_group_in = QtCore.QParallelAnimationGroup()
        _anim_group_in.addAnimation(_fade_overlay)
        _anim_group_in.addAnimation(_fade_card)

        def _on_open_done():
            card.setGraphicsEffect(None)

        _anim_group_in.finished.connect(_on_open_done)
        dialog._open_anim = _anim_group_in
        _anim_group_in.start()

        # ═══════════════════════════════════════════════════════════════
        # ПЛАВНОЕ ЗАКРЫТИЕ: fade-out overlay + карточка
        # ═══════════════════════════════════════════════════════════════
        def _fade_and_close(callback=None):
            # Если анимация открытия ещё идёт — останавливаем
            if dialog._open_anim and dialog._open_anim.state() == QtCore.QAbstractAnimation.State.Running:
                dialog._open_anim.stop()
            card.setGraphicsEffect(None)  # убираем старый эффект если остался

            close_eff = QtWidgets.QGraphicsOpacityEffect(card)
            card.setGraphicsEffect(close_eff)
            close_eff.setOpacity(1.0)

            _co = QtCore.QPropertyAnimation(close_eff, b"opacity")
            _co.setDuration(180)
            _co.setStartValue(1.0)
            _co.setEndValue(0.0)
            _co.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            _fo = QtCore.QPropertyAnimation(dialog, b"windowOpacity")
            _fo.setDuration(200)
            _fo.setStartValue(dialog.windowOpacity())
            _fo.setEndValue(0.0)
            _fo.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            _group = QtCore.QParallelAnimationGroup()
            _group.addAnimation(_co)
            _group.addAnimation(_fo)

            def _on_close_done():
                card.setGraphicsEffect(None)
                dialog.accept()
                if callback:
                    callback()

            _group.finished.connect(_on_close_done)
            dialog._close_anim = _group
            _group.start()

        # Клик по затемнённому фону — закрывает
        class _OverlayClickFilter(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                    if obj is dialog:
                        # Клик вне карточки → закрываем
                        cp = event.position().toPoint() if hasattr(event, "position") else event.pos()
                        if not card.geometry().contains(cp):
                            _fade_and_close()
                            return True
                return False

        _click_filter = _OverlayClickFilter(dialog)
        dialog.installEventFilter(_click_filter)
        dialog._click_filter = _click_filter  # держим ссылку

        x_btn.clicked.connect(lambda: _fade_and_close())
        close_btn.clicked.connect(lambda: _fade_and_close())

        # ── Выбор LLaMA ─────────────────────────────────────────────
        def _select_llama():
            def _after():
                if not llama_installed:
                    # LLaMA не скачана — предлагаем скачать
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "LLaMA 3 не установлена",
                        "⚠️ LLaMA 3 ещё не скачана (~4.7 GB).\n\nХотите скачать её сейчас?\nМожно выбрать диск для сохранения.",
                        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        dl_dialog = LlamaDownloadDialog(self)
                        dl_dialog.download_finished.connect(
                            lambda ok, msg: (
                                self.change_ai_model("llama3"),
                                self._save_first_launch_flag()
                            ) if ok else None
                        )
                        dl_dialog.exec()
                elif llama_handler.CURRENT_AI_MODEL_KEY != "llama3":
                    self.change_ai_model("llama3")
            _fade_and_close(_after)

        # ── Выбор DeepSeek ──────────────────────────────────────────
        def _select_deepseek():
            def _after():
                if llama_handler.CURRENT_AI_MODEL_KEY == "deepseek":
                    return
                if deepseek_installed:
                    self.change_ai_model("deepseek")
                else:
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "Модель не найдена",
                        "⚠️ DeepSeek не скачан.\n\nХотите скачать его сейчас? (~4.1 GB, несколько минут)",
                        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        self._start_deepseek_download()
            _fade_and_close(_after)

        # ── Выбор Mistral ───────────────────────────────────────────
        def _select_mistral():
            def _after():
                if llama_handler.CURRENT_AI_MODEL_KEY == "mistral":
                    return
                if mistral_installed:
                    self.change_ai_model("mistral")
                else:
                    reply = QtWidgets.QMessageBox.question(
                        self,
                        "Модель не найдена",
                        "⚠️ Mistral Nemo 12B не скачан (~7.1 GB).\n\n"
                        "Хотите скачать его сейчас?",
                        QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                        QtWidgets.QMessageBox.StandardButton.Yes
                    )
                    if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                        self._start_mistral_download()
            _fade_and_close(_after)

        llama_btn.clicked.connect(_select_llama)
        deepseek_btn.clicked.connect(_select_deepseek)
        mistral_btn.clicked.connect(_select_mistral)

        dialog.exec()

    def _start_deepseek_download(self):
        """Открывает диалог скачивания DeepSeek и после успеха активирует модель."""
        dl_dialog = DeepSeekDownloadDialog(self)
        dl_dialog.download_finished.connect(
            lambda success, msg: self._on_deepseek_downloaded(success, msg)
        )
        dl_dialog.exec()

    def _on_deepseek_downloaded(self, success: bool, message: str):
        """Вызывается после завершения скачивания DeepSeek."""
        if success:
            self.change_ai_model("deepseek")
        else:
            print(f"[MODEL] Скачивание DeepSeek не удалось: {message}")

    def _start_mistral_download(self):
        """Открывает диалог скачивания Mistral Nemo и после успеха активирует модель."""
        dl_dialog = MistralDownloadDialog(self)
        dl_dialog.download_finished.connect(
            lambda success, msg: self._on_mistral_downloaded(success, msg)
        )
        dl_dialog.exec()

    def _on_mistral_downloaded(self, success: bool, message: str):
        """Вызывается после завершения скачивания Mistral Nemo."""
        if success:
            self.change_ai_model("mistral")
        else:
            print(f"[MODEL] Скачивание Mistral Nemo не удалось: {message}")

    def _start_model_download(self, model_key: str):
        """
        Универсальный метод запуска скачивания модели по ключу.
        Используется из меню перегенерации.
        """
        if model_key == "llama3":
            dl = LlamaDownloadDialog(self)
            dl.download_finished.connect(
                lambda ok, msg: self.change_ai_model("llama3") if ok else None
            )
            dl.exec()
        elif model_key == "deepseek":
            self._start_deepseek_download()
        elif model_key == "mistral":
            self._start_mistral_download()

    # ─────────────────────────────────────────────────────────────────
    def _delete_model(self, model_key: str, model_name: str, ollama_name: str):
        """
        Удаляет модель ФИЗИЧЕСКИ С ДИСКА:
          1. Находит реальную папку с файлами Ollama
          2. Запускает «ollama rm» (удаляет из реестра)
          3. Дополнительно вручную удаляет manifest и blob-файлы
        """
        print(f"[DELETE] Удаляем {model_name} (ollama: {ollama_name}) …")

        prog = QtWidgets.QProgressDialog(
            f"Удаление {model_name}…", None, 0, 0, self
        )
        prog.setWindowTitle("Удаление модели")
        prog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        if IS_WINDOWS:
            prog.setWindowFlags(
                QtCore.Qt.WindowType.Dialog |
                QtCore.Qt.WindowType.WindowTitleHint
            )
        prog.show()
        QtWidgets.QApplication.processEvents()

        err = ""
        rm_ok = False

        # ── 1. Запускаем ollama rm ──────────────────────────────────
        try:
            kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if IS_WINDOWS:
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            proc = subprocess.run(
                ["ollama", "rm", ollama_name], timeout=60, **kwargs
            )
            rm_ok = (proc.returncode == 0)
            if not rm_ok:
                err = (proc.stdout or "").strip() or f"Код {proc.returncode}"
                print(f"[DELETE] ollama rm вернул ошибку: {err}")
        except FileNotFoundError:
            err = "Ollama не найдена."
        except subprocess.TimeoutExpired:
            err = "Тайм-аут команды ollama rm"
        except Exception as e:
            err = str(e)

        # ── 2. Физически удаляем файлы с диска ─────────────────────
        #    (делаем даже если ollama rm упал — вдруг файлы всё равно остались)
        models_dir = get_ollama_models_dir()
        bytes_freed, deleted = delete_model_files_from_disk(ollama_name, models_dir)
        print(f"[DELETE] Удалено файлов: {len(deleted)}, "
              f"освобождено: {bytes_freed / 1024**3:.2f} GB")
        print(f"[DELETE] Папка моделей: {models_dir}")

        prog.close()

        # ── 3. Итог ─────────────────────────────────────────────────
        fully_ok = rm_ok or (len(deleted) > 0)
        if not fully_ok:
            QtWidgets.QMessageBox.critical(
                self, "Ошибка удаления",
                f"❌ Не удалось удалить {model_name}.\n\n{err}\n\n"
                f"Проверьте что Ollama запущена и попробуйте снова.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            return

        was_active = (llama_handler.CURRENT_AI_MODEL_KEY == model_key)

        ALL_MODELS = {
            "llama3":   ("llama3",           "LLaMA 3"),
            "deepseek": (DEEPSEEK_MODEL_NAME, "DeepSeek"),
        }
        remaining = {
            k: dname
            for k, (oname, dname) in ALL_MODELS.items()
            if k != model_key and check_model_in_ollama(oname)
        }

        freed_str = f"\n\nОсвобождено: {bytes_freed / 1024**3:.1f} GB" if bytes_freed > 0 else ""

        if not remaining:
            QtWidgets.QMessageBox.warning(
                self, "⚠️ Модели не установлены",
                f"✅ {model_name} удалена с диска.{freed_str}\n\n"
                "⚠️ У вас не установлено ни одной модели ИИ.\n\n"
                "Без модели пользоваться ассистентом невозможно.\n"
                "Откройте «Выбор модели» и скачайте любую модель.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            save_settings({"first_launch_done": False})
        else:
            other_key  = list(remaining.keys())[0]
            other_name = remaining[other_key]
            msg = f"✅ {model_name} успешно удалена с диска.{freed_str}"
            if was_active:
                msg += f"\n\nПрограмма переключена на {other_name}."
            QtWidgets.QMessageBox.information(
                self, "Модель удалена", msg,
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            if was_active:
                self.change_ai_model(other_key)

        self._refresh_model_ui()

    def _refresh_model_ui(self):
        """Обновляет UI-элементы, зависящие от текущей активной модели."""
        try:
            # Пробуем обновить заголовок/лейбл если они есть
            for attr in ("model_label", "ai_name_label", "header_model_lbl",
                         "current_model_label", "model_name_lbl"):
                w = getattr(self, attr, None)
                if w and hasattr(w, "setText"):
                    try:
                        w.setText(get_current_display_name())
                    except Exception:
                        pass
        except Exception as e:
            print(f"[MODEL_UI] _refresh_model_ui: {e}")

    def animate_mode_change(self, new_mode: str):
        """Плавная смена режима: fade-out → смена текста → fade-in."""
        if self.ai_mode == new_mode:
            return
        self.ai_mode = new_mode
        self.deep_thinking = new_mode != AI_MODE_FAST
        print(f"[MODE] Анимация смены режима → {new_mode}")
        for attr in ('_mode_fade_out', '_mode_fade_in'):
            anim = getattr(self, attr, None)
            if anim:
                anim.stop()
        effect = QtWidgets.QGraphicsOpacityEffect(self.mode_btn)
        self.mode_btn.setGraphicsEffect(effect)
        fade_out = QtCore.QPropertyAnimation(effect, b"opacity")
        fade_out.setDuration(110)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        fade_in = QtCore.QPropertyAnimation(effect, b"opacity")
        fade_in.setDuration(180)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)
        fade_out.finished.connect(lambda: self.mode_btn.setText(new_mode))
        fade_out.finished.connect(fade_in.start)
        fade_in.finished.connect(lambda: self.mode_btn.setGraphicsEffect(None))
        self._mode_fade_out = fade_out
        self._mode_fade_in = fade_in
        fade_out.start()

    def show_mode_menu(self):
        """Показать меню выбора режима работы AI с премиум iOS-like анимацией"""
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: АНИМАЦИЯ НАЖАТИЯ КНОПКИ (opacity pulse — не конфликтует с layout)
        # ═══════════════════════════════════════════════════════════════
        _mode_press_eff = QtWidgets.QGraphicsOpacityEffect(self.mode_btn)
        self.mode_btn.setGraphicsEffect(_mode_press_eff)
        _mode_press_eff.setOpacity(1.0)
        _mode_pulse = QtCore.QPropertyAnimation(_mode_press_eff, b"opacity")
        _mode_pulse.setDuration(180)
        _mode_pulse.setKeyValueAt(0.0, 1.0)
        _mode_pulse.setKeyValueAt(0.4, 0.55)
        _mode_pulse.setKeyValueAt(1.0, 1.0)
        _mode_pulse.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        _mode_pulse.finished.connect(lambda: self.mode_btn.setGraphicsEffect(None))
        _mode_pulse.start()
        self._mode_pulse_anim = _mode_pulse  # держим ссылку
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: СОЗДАНИЕ МЕНЮ
        # ═══════════════════════════════════════════════════════════════
        menu = QtWidgets.QMenu(self)
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Прозрачное меню (работает на Windows и macOS/Linux)
        menu.setWindowFlags(QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint)
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        
        # Адаптивные стили в зависимости от темы
        if is_dark:
            # Тёмная тема
            menu.setStyleSheet("""
                QMenu {
                    background: rgba(30, 30, 35, 245);
                    border: 1px solid rgba(60, 60, 70, 200);
                    border-radius: 16px;
                    padding: 10px;
                }
                QMenu::item {
                    padding: 14px 30px;
                    border-radius: 12px;
                    color: #e0e0e0;
                    font-family: "Segoe UI Variable", "Segoe UI", Inter, -apple-system, sans-serif;
                    font-size: 15px;
                    font-weight: 600;
                    margin: 4px;
                    background: transparent;
                }
                QMenu::item:selected {
                    background: rgba(60, 60, 70, 210);
                    color: #ffffff;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(80, 80, 100, 100);
                    margin: 4px 12px;
                }
                QMenu::indicator { width: 0px; height: 0px; }
            """)
        else:
            # Светлая тема
            menu.setStyleSheet("""
                QMenu {
                    background: rgba(255, 255, 255, 245);
                    border: 1px solid rgba(220, 220, 230, 200);
                    border-radius: 16px;
                    padding: 10px;
                }
                QMenu::item {
                    padding: 14px 30px;
                    border-radius: 12px;
                    color: #1a202c;
                    font-family: "Segoe UI Variable", "Segoe UI", Inter, -apple-system, sans-serif;
                    font-size: 15px;
                    font-weight: 600;
                    margin: 4px;
                    background: transparent;
                }
                QMenu::item:selected {
                    background: rgba(235, 235, 245, 210);
                    color: #0f172a;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(180, 185, 200, 130);
                    margin: 4px 12px;
                }
                QMenu::indicator { width: 0px; height: 0px; }
            """)
        
        # ── Карточка модели через QWidgetAction (кликабельная!) ──
        _model_widget_action = QtWidgets.QWidgetAction(menu)
        _model_card = QtWidgets.QPushButton()
        _model_card.setFixedHeight(52)
        _model_card.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

        _current_display = get_current_display_name()

        if is_dark:
            _card_bg     = "rgba(55, 55, 70, 0.7)"
            _card_bg_h   = "rgba(70, 70, 90, 0.85)"
            _card_border = "rgba(80, 80, 110, 0.6)"
            _icon_color  = "#9aa8cc"
            _name_color  = "#d0d8f0"
            _sub_color   = "#7888aa"
        else:
            _card_bg     = "rgba(235, 238, 250, 0.85)"
            _card_bg_h   = "rgba(220, 225, 245, 0.95)"
            _card_border = "rgba(200, 208, 230, 0.8)"
            _icon_color  = "#6677aa"
            _name_color  = "#1a2040"
            _sub_color   = "#8899bb"

        _model_card.setStyleSheet(f"""
            QPushButton {{
                background: {_card_bg};
                border: 1px solid {_card_border};
                border-radius: 10px;
                text-align: left;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: {_card_bg_h};
                border: 1px solid rgba(102, 126, 234, 0.5);
            }}
        """)

        # Внутренний layout карточки
        _cl = QtWidgets.QHBoxLayout(_model_card)
        _cl.setContentsMargins(12, 0, 14, 0)
        _cl.setSpacing(10)
        _cl.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter)

        _icon_lbl = QtWidgets.QLabel()
        _icon_lbl.setFixedSize(26, 26)
        _icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        _icon_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _icon_lbl.setStyleSheet("background: transparent; border: none;")
        # Логотип текущей модели — берём из встроенного base64
        _model_px = _get_model_logo_pixmap(llama_handler.CURRENT_AI_MODEL_KEY, size=22)
        if not _model_px.isNull():
            _icon_lbl.setPixmap(_model_px)
        else:
            _icon_lbl.setText(llama_handler.SUPPORTED_MODELS.get(
                llama_handler.CURRENT_AI_MODEL_KEY, ("", "?"))[1][:1])
            _icon_lbl.setStyleSheet(
                f"background: transparent; border: none; font-size: 15px; font-weight: 700; color: {_icon_color};"
            )
        _cl.addWidget(_icon_lbl, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        _text_col = QtWidgets.QVBoxLayout()
        _text_col.setSpacing(1)
        _text_col.setContentsMargins(0, 8, 0, 8)

        _sub_lbl = QtWidgets.QLabel("Текущая модель  ›")
        _sub_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"color: {_sub_color}; font-size: 10px; font-weight: 400;"
        )
        _sub_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _text_col.addWidget(_sub_lbl, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        _name_lbl = QtWidgets.QLabel(_current_display)
        _name_lbl.setStyleSheet(
            f"background: transparent; border: none; "
            f"color: {_name_color}; font-size: 14px; font-weight: 700;"
        )
        _name_lbl.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _text_col.addWidget(_name_lbl, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        _cl.addLayout(_text_col, 0)
        _cl.addStretch()

        # При клике на карточку — открываем выбор модели
        _model_card.clicked.connect(lambda: (menu.close(), self.show_model_selector()))

        _wrap = QtWidgets.QWidget()
        _wl = QtWidgets.QVBoxLayout(_wrap)
        _wl.setContentsMargins(4, 4, 4, 4)
        _wl.addWidget(_model_card)

        _model_widget_action.setDefaultWidget(_wrap)
        menu.addAction(_model_widget_action)
        menu.addSeparator()

        # ── Режимы: QWidgetAction с кастомным рендером ───────────────────────
        # QMenu::item никогда не выглядит хорошо — используем виджеты напрямую
        _MENU_W = 240  # фиксированная ширина строк

        _mode_cfg = [
            (AI_MODE_FAST,     "⚡", "Быстрый",   AI_MODE_FAST),
            (AI_MODE_THINKING, "🧠", "Думающий",  AI_MODE_THINKING),
            (AI_MODE_PRO,      "🚀", "Про",        AI_MODE_PRO),
        ]

        if is_dark:
            _row_bg_active  = "rgba(80, 82, 110, 0.55)"
            _row_border_act = "rgba(110, 120, 210, 0.40)"
            _row_hover      = "rgba(58, 58, 75, 0.70)"
            _txt_active     = "#ffffff"
            _txt_normal     = "#c8c8de"
            _chk_col        = "#8899ff"
        else:
            _row_bg_active  = "rgba(225, 228, 252, 0.80)"
            _row_border_act = "rgba(140, 155, 230, 0.45)"
            _row_hover      = "rgba(238, 240, 252, 0.90)"
            _txt_active     = "#1a1a3a"
            _txt_normal     = "#3a3a5a"
            _chk_col        = "#5566cc"

        _mode_btns = []
        for _mk2, _emoji, _label, _target in _mode_cfg:
            _active = (self.ai_mode == _mk2)

            _wa = QtWidgets.QWidgetAction(menu)
            _row = QtWidgets.QWidget()
            _row.setFixedSize(_MENU_W, 46)

            # Фон активного пункта — скруглённый pill
            if _active:
                _row.setStyleSheet(f"""
                    QWidget {{
                        background: {_row_bg_active};
                        border: 1px solid {_row_border_act};
                        border-radius: 10px;
                    }}
                """)
            else:
                _row.setStyleSheet("""
                    QWidget { background: transparent; border: none; border-radius: 10px; }
                    QWidget:hover { background: """ + _row_hover + """; }
                """)

            _rl = QtWidgets.QHBoxLayout(_row)
            _rl.setContentsMargins(14, 0, 14, 0)
            _rl.setSpacing(11)

            # Emoji
            _e = QtWidgets.QLabel(_emoji)
            _e.setFixedSize(26, 26)
            _e.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            _e.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            _e.setStyleSheet("background: transparent; border: none; font-size: 16px;")
            _rl.addWidget(_e)

            # Label
            _t = QtWidgets.QLabel(_label)
            _t.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            _t.setStyleSheet(
                f"background: transparent; border: none; "
                f"color: {_txt_active if _active else _txt_normal}; "
                f"font-size: 14px; font-weight: {'700' if _active else '600'};"
            )
            _rl.addWidget(_t)
            _rl.addStretch()

            # Галочка активного
            if _active:
                _c = QtWidgets.QLabel("✓")
                _c.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                _c.setStyleSheet(
                    f"background: transparent; border: none; "
                    f"color: {_chk_col}; font-size: 13px; font-weight: 700;"
                )
                _rl.addWidget(_c)

            _wa.setDefaultWidget(_row)
            menu.addAction(_wa)

            # Обёртка: делаем строку кликабельной через btn поверх
            _btn = QtWidgets.QPushButton(_row)
            _btn.setGeometry(0, 0, _MENU_W, 46)
            _btn.setFlat(True)
            _btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
            _btn.setStyleSheet("QPushButton { background: transparent; border: none; }")
            _mode_btns.append((_btn, _target))

        # Подключаем обработчики
        for _btn, _target in _mode_btns:
            def _h(checked=False, k=_target):
                menu.close()
                self.animate_mode_change(k)
            _btn.clicked.connect(_h)

        # stub-переменные (triggered.connect ниже на них не вызывается)
        fast_action     = None
        thinking_action = None
        pro_action      = None
        
        # Получаем позицию кнопки
        button_rect = self.mode_btn.rect()
        button_global_pos = self.mode_btn.mapToGlobal(button_rect.bottomLeft())
        
        # Получаем размер меню
        menu.adjustSize()
        menu_size = menu.sizeHint()
        menu_height = menu_size.height()
        menu_width = menu_size.width()
        
        # Получаем геометрию окна приложения
        window_geometry = self.geometry()
        window_top = self.mapToGlobal(QtCore.QPoint(0, 0)).y()
        window_bottom = self.mapToGlobal(QtCore.QPoint(0, window_geometry.height())).y()
        
        # Вычисляем позицию ВВЕРХ от кнопки
        menu_pos_up = QtCore.QPoint(
            button_global_pos.x() - (menu_width - self.mode_btn.width()) // 2,  # Центрируем по кнопке
            button_global_pos.y() - self.mode_btn.height() - menu_height - 8
        )
        
        # Проверяем, выходит ли меню за верхнюю границу окна
        if menu_pos_up.y() < window_top + 80:  # 80px отступ от верха (title bar)
            # Если выходит за верх - показываем ВНИЗ от кнопки
            menu_pos = QtCore.QPoint(
                button_global_pos.x() - (menu_width - self.mode_btn.width()) // 2,
                button_global_pos.y() + 8
            )
            print("[MODE_MENU] Меню открывается вниз (не хватает места сверху)")
        else:
            # Показываем вверх
            menu_pos = menu_pos_up
            print("[MODE_MENU] Меню открывается вверх")
        
        # Плавное появление меню через fade + scale
        # Создаём эффект прозрачности
        opacity_effect = QtWidgets.QGraphicsOpacityEffect(menu)
        menu.setGraphicsEffect(opacity_effect)
        opacity_effect.setOpacity(0.0)
        
        # Анимация прозрачности
        opacity_anim = QtCore.QPropertyAnimation(opacity_effect, b"opacity")
        opacity_anim.setDuration(280)
        opacity_anim.setStartValue(0.0)
        opacity_anim.setEndValue(1.0)
        opacity_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        
        # ═══════════════════════════════════════════════════════════════
        # SCALE АНИМАЦИЯ - меню появляется снизу вверх с пружинным эффектом
        # ═══════════════════════════════════════════════════════════════
        # Создаём dummy property для анимации масштаба
        class ScaleAnimator(QtCore.QObject):
            valueChanged = QtCore.pyqtSignal(float)
            
            def __init__(self):
                super().__init__()
                self._value = 0.0
            
            def getValue(self):
                return self._value
            
            def setValue(self, val):
                self._value = val
                self.valueChanged.emit(val)
            
            value = QtCore.pyqtProperty(float, getValue, setValue)
        
        scale_animator = ScaleAnimator()
        scale_anim = QtCore.QPropertyAnimation(scale_animator, b"value")
        scale_anim.setDuration(350)
        scale_anim.setStartValue(0.85)
        scale_anim.setEndValue(1.0)
        scale_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)  # iOS-like spring
        
        # Подключаем обновление геометрии при изменении scale
        def update_menu_scale(value):
            try:
                # Получаем текущую геометрию
                if not hasattr(menu, '_original_height'):
                    menu._original_height = menu_height
                
                # Вычисляем новую высоту
                new_height = int(menu._original_height * value)
                
                # Обновляем позицию (anchor point - центр кнопки)
                button_center_y = button_global_pos.y() - self.mode_btn.height() // 2
                
                # Позиционируем меню относительно центра
                if menu_pos.y() < button_center_y:
                    # Меню вверху - растём вниз
                    new_y = button_global_pos.y() - self.mode_btn.height() - new_height - 8
                else:
                    # Меню внизу - растём вверх
                    new_y = button_global_pos.y() + 8
                
                # Устанавливаем новую геометрию
                menu.setGeometry(
                    menu_pos.x(),
                    new_y,
                    menu_width,
                    new_height
                )
            except RuntimeError:
                pass
        
        scale_animator.valueChanged.connect(update_menu_scale)
        
        # Группа анимаций
        anim_group = QtCore.QParallelAnimationGroup()
        anim_group.addAnimation(opacity_anim)
        anim_group.addAnimation(scale_anim)
        
        # Сохраняем ссылки для предотвращения garbage collection
        menu._anim_group = anim_group
        menu._opacity_effect = opacity_effect
        menu._scale_animator = scale_animator

        # ── Режимы управляются через _btn.clicked (см. выше) ────────────────

        # ── Анимация закрытия: screenshot-proxy паттерн ──
        # menu.grab() рендерит виджет со всеми стилями (скругления, прозрачность).
        # Qt закрывает оригинальное меню — proxy плавно анимируется на его месте.
        _close_started = [False]

        def _animate_mode_close():
            if _close_started[0]:
                return
            _close_started[0] = True

            cur_geo = menu.geometry()

            # grab() рендерит меню с его CSS (border-radius, прозрачность)
            try:
                px = menu.grab()
            except Exception:
                px = None

            # Proxy-виджет с прозрачным фоном поверх всего
            class _ProxyWidget(QtWidgets.QWidget):
                def __init__(self, pixmap, geo):
                    super().__init__(
                        None,
                        QtCore.Qt.WindowType.Tool |
                        QtCore.Qt.WindowType.FramelessWindowHint |
                        QtCore.Qt.WindowType.WindowStaysOnTopHint
                    )
                    self._px = pixmap
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
                    self.setGeometry(geo)

                def paintEvent(self, event):
                    if self._px:
                        from PyQt6 import QtGui
                        p = QtGui.QPainter(self)
                        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                        # Рисуем с тем же масштабом что и текущий размер виджета
                        p.drawPixmap(self.rect(), self._px)
                        p.end()

            proxy = _ProxyWidget(px, cur_geo)
            proxy.show()
            proxy.raise_()

            # Fade-out
            _c_eff = QtWidgets.QGraphicsOpacityEffect(proxy)
            proxy.setGraphicsEffect(_c_eff)
            _c_eff.setOpacity(1.0)

            _c_op = QtCore.QPropertyAnimation(_c_eff, b"opacity")
            _c_op.setDuration(180)
            _c_op.setStartValue(1.0)
            _c_op.setEndValue(0.0)
            _c_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            # Scale-down вниз (сжатие к кнопке)
            end_geo = QtCore.QRect(
                cur_geo.x(),
                cur_geo.y() + int(cur_geo.height() * 0.12),
                cur_geo.width(),
                int(cur_geo.height() * 0.88)
            )
            _c_geo = QtCore.QPropertyAnimation(proxy, b"geometry")
            _c_geo.setDuration(180)
            _c_geo.setStartValue(cur_geo)
            _c_geo.setEndValue(end_geo)
            _c_geo.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            def _on_proxy_done():
                try:
                    proxy.close()
                except Exception:
                    pass
                self.mode_btn.clearFocus()
                self.input_field.setFocus()

            _c_op.finished.connect(_on_proxy_done)
            _c_op.start()
            _c_geo.start()
            proxy._anims = [_c_op, _c_geo, _c_eff]

        menu.aboutToHide.connect(_animate_mode_close)

        # Запускаем анимацию появления после небольшой задержки
        QtCore.QTimer.singleShot(120, anim_group.start)

        # popup() — не блокирует event loop
        menu.popup(menu_pos)
    
    def eventFilter(self, obj, event):
        """
        Фильтр событий для:
        1. Обновления кнопки "вниз" после ручного скролла
        2. Позиционирования floating кнопки при resize
        3. Автозакрытия sidebar при клике вне его
        
        ПРОСТАЯ АРХИТЕКТУРА:
        - Wheel события НИКОГДА не блокируются
        - После wheel → обновляем кнопку через invokeMethod
        - При resize → обновляем позицию кнопки
        - НЕТ сложной синхронизации, НЕТ флагов
        """
        # ═══════════════════════════════════════════════
        # ОБРАБОТКА WHEEL СОБЫТИЙ (прокрутка колесиком)
        # ═══════════════════════════════════════════════
        # Проверяем что это viewport нашего scroll_area
        if obj == self.scroll_area.viewport():
            # Если это wheel событие
            if event.type() == QtCore.QEvent.Type.Wheel:
                # ═══════════════════════════════════════════════
                # НИКОГДА НЕ БЛОКИРУЕМ WHEEL
                # ═══════════════════════════════════════════════
                # Layout завершается независимо от действий пользователя
                # Пользователь может скроллить в любой момент
                # Обрабатываем wheel событие стандартно
                result = super().eventFilter(obj, event)
                
                # ПОСЛЕ обработки wheel события обновляем кнопку
                # Используем QMetaObject.invokeMethod для отложенного вызова
                # чтобы кнопка обновилась ПОСЛЕ полной обработки скролла
                # (scrollbar.value() уже изменился)
                # update_scroll_button_visibility сама проверит _layout_in_progress
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_update_button_after_scroll",
                    QtCore.Qt.ConnectionType.QueuedConnection
                )
                
                return result
        
        # ═══════════════════════════════════════════════
        # ОБРАБОТКА RESIZE SCROLL_AREA (изменение размера)
        # ═══════════════════════════════════════════════
        if obj == self.scroll_area and event.type() == QtCore.QEvent.Type.Resize:
            if hasattr(self, 'scroll_to_bottom_btn'):
                # Обновляем позицию кнопки при resize
                # Это единственное место где вызывается update_position
                self.scroll_to_bottom_btn.update_position(
                    self.scroll_area.width(),
                    self.scroll_area.height()
                )
        
        # ═══════════════════════════════════════════════
        # АВТОЗАКРЫТИЕ SIDEBAR (клик вне sidebar)
        # ═══════════════════════════════════════════════
        # Проверяем, открыт ли sidebar
        if self.sidebar.width() > 0:
            # Если событие - клик мышью
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                # Закрываем sidebar
                self.toggle_sidebar()
        
        # Для всех остальных случаев - стандартная обработка
        return super().eventFilter(obj, event)
    
    @QtCore.pyqtSlot()
    def _update_button_after_scroll(self):
        """
        Обновляет layout и видимость кнопки "вниз" после ручного скролла.
        
        КРИТИЧНО:
        - Вызывается через QMetaObject.invokeMethod после wheel события
        - Гарантирует что скролл полностью обработан
        - При ручном скролле ВСЕГДА обновляет layout (как при переключении чата)
        - Это гарантирует корректное отображение всех накопленных сообщений и кнопки
        """
        # ═══════════════════════════════════════════════════════════════
        # ОБНОВЛЕНИЕ LAYOUT ПРИ РУЧНОМ СКРОЛЛЕ
        # ═══════════════════════════════════════════════════════════════
        # Сохраняем текущую позицию скролла
        scrollbar = self.scroll_area.verticalScrollBar()
        current_value = scrollbar.value()
        
        # Полное обновление layout (как при переключении чата)
        self.messages_layout.invalidate()
        self.messages_layout.activate()
        self.messages_widget.updateGeometry()
        
        # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: update() вместо repaint() + processEvents()
        self.scroll_area.viewport().update()
        
        # Восстанавливаем позицию скролла
        scrollbar.setValue(current_value)
        
        # Теперь обновляем кнопку после завершения layout
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.update_scroll_button_visibility()
    
    def toggle_thinking(self, state=None):
        # Блокируем переключение во время генерации
        if self.is_generating:
            return
        
        # Если вызвано напрямую (из меню), просто используем текущее состояние
        if state is None:
            return
        
        self.deep_thinking = (state == QtCore.Qt.CheckState.Checked.value)

    def toggle_search(self, state=None):
        # Блокируем переключение во время генерации
        if self.is_generating:
            return
        
        # Если вызвано напрямую (из меню), просто используем текущее состояние
        if state is None:
            return
        
        self.use_search = (state == QtCore.Qt.CheckState.Checked.value)
    
    def show_attach_menu(self):
        """Показать меню с опциями Search и Attach file с премиум iOS-like анимацией + blur эффект"""
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: АНИМАЦИЯ НАЖАТИЯ КНОПКИ «+» (opacity pulse — не конфликтует с layout)
        # ═══════════════════════════════════════════════════════════════
        _attach_press_eff = QtWidgets.QGraphicsOpacityEffect(self.attach_btn)
        self.attach_btn.setGraphicsEffect(_attach_press_eff)
        _attach_press_eff.setOpacity(1.0)
        _attach_pulse = QtCore.QPropertyAnimation(_attach_press_eff, b"opacity")
        _attach_pulse.setDuration(180)
        _attach_pulse.setKeyValueAt(0.0, 1.0)
        _attach_pulse.setKeyValueAt(0.4, 0.55)
        _attach_pulse.setKeyValueAt(1.0, 1.0)
        _attach_pulse.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        _attach_pulse.finished.connect(lambda: self.attach_btn.setGraphicsEffect(None))
        _attach_pulse.start()
        self._attach_pulse_anim = _attach_pulse  # держим ссылку
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: СОЗДАНИЕ МЕНЮ
        # ═══════════════════════════════════════════════════════════════
        menu = QtWidgets.QMenu(self)
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Прозрачное меню без артефактов (работает на Windows и macOS/Linux)
        menu.setWindowFlags(QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint)
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        
        # Адаптивные стили в зависимости от темы
        if is_dark:
            # Тёмная тема - стеклянный эффект
            menu.setStyleSheet("""
                QMenu {
                    background: rgba(30, 30, 35, 245);
                    border: 1px solid rgba(60, 60, 70, 200);
                    border-radius: 20px;
                    padding: 12px;
                }
                QMenu::item {
                    padding: 14px 45px;
                    border-radius: 12px;
                    color: #e0e0e0;
                    font-size: 15px;
                    font-weight: 600;
                    margin: 4px;
                    background: transparent;
                    min-width: 190px;
                    max-width: 190px;
                }
                QMenu::item:selected {
                    background: rgba(60, 60, 70, 210);
                    color: #ffffff;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(80, 80, 90, 128);
                    margin: 8px 20px;
                }
            """)
        else:
            # Светлая тема - стеклянный эффект
            menu.setStyleSheet("""
                QMenu {
                    background: rgba(255, 255, 255, 245);
                    border: 1px solid rgba(220, 220, 230, 200);
                    border-radius: 20px;
                    padding: 12px;
                }
                QMenu::item {
                    padding: 14px 45px;
                    border-radius: 12px;
                    color: #1a202c;
                    font-size: 15px;
                    font-weight: 600;
                    margin: 4px;
                    background: transparent;
                    min-width: 190px;
                    max-width: 190px;
                }
                QMenu::item:selected {
                    background: rgba(235, 235, 245, 210);
                    color: #0f172a;
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(200, 200, 210, 153);
                    margin: 8px 20px;
                }
            """)
        
        # FORCED SEARCH - явное указание режима принудительного поиска
        search_label = "🔴 Принудительный поиск" if self.use_search else "🔍 Умный поиск"
        search_action = menu.addAction(search_label)
        search_action.setCheckable(True)
        search_action.setChecked(self.use_search)
        
        # Разделитель
        menu.addSeparator()
        
        # Attach file опция — показываем количество прикреплённых файлов
        files_count = len(self.attached_files)
        if files_count > 0:
            if files_count >= 5:
                # Достигнут лимит - можно только открепить
                file_action = menu.addAction(f"📎 Файлов: {files_count}/5 (максимум)")
                file_action.setEnabled(False)
                clear_action = menu.addAction(f"✕  Открепить все ({files_count})")
            else:
                # Можно добавить ещё файлы
                file_action = menu.addAction(f"📎 Добавить файл ({files_count}/5)")
                clear_action = menu.addAction(f"✕  Открепить все ({files_count})")
        else:
            file_action = menu.addAction("📎 Прикрепить файл")
            clear_action = None
        
        # Вычисляем позицию меню НАД кнопкой с edge avoidance
        button_rect = self.attach_btn.rect()
        button_global_pos = self.attach_btn.mapToGlobal(button_rect.topLeft())
        button_center = self.attach_btn.mapToGlobal(button_rect.center())
        
        # Размеры меню
        menu_height = 150
        # Рассчитываем правильную ширину меню:
        # Item: 190px (content) + 90px (padding 45px*2) + 8px (margin 4px*2) = 288px
        # Menu: 288px + 24px (padding 12px*2) = 312px
        menu_width = 320  # С небольшим запасом
        
        # ═══════════════════════════════════════════════════════════════
        # EDGE AVOIDANCE - гарантируем что меню не выходит за границы окна
        # ═══════════════════════════════════════════════════════════════
        
        # Получаем размеры окна приложения
        app_geometry = self.geometry()
        window_global_pos = self.mapToGlobal(QtCore.QPoint(0, 0))
        window_width = app_geometry.width()
        
        # Минимальный отступ от краёв окна
        EDGE_PADDING = 12
        
        # Вычисляем идеальную позицию (центр меню по центру кнопки)
        ideal_menu_x = button_center.x() - menu_width // 2
        
        # Применяем clamp - ограничиваем позицию границами окна
        # Левая граница: минимум EDGE_PADDING от левого края окна
        min_x = window_global_pos.x() + EDGE_PADDING
        # Правая граница: максимум так, чтобы правый край меню был на EDGE_PADDING от правого края окна
        max_x = window_global_pos.x() + window_width - menu_width - EDGE_PADDING
        
        # Clamp позиции
        clamped_menu_x = max(min_x, min(ideal_menu_x, max_x))
        
        # Финальная позиция меню
        menu_pos = QtCore.QPoint(
            clamped_menu_x,  # X с edge avoidance
            button_global_pos.y() - menu_height - 8  # Y: над кнопкой с отступом
        )
        
        # Отладочная информация
        print(f"[POPOVER] Позиционирование меню:")
        print(f"  Кнопка центр: x={button_center.x()}")
        print(f"  Окно: x={window_global_pos.x()}, width={window_width}")
        print(f"  Меню ширина: {menu_width}")
        print(f"  Идеальная позиция: x={ideal_menu_x}")
        print(f"  Границы: min_x={min_x}, max_x={max_x}")
        print(f"  Финальная позиция: x={clamped_menu_x}")
        print(f"  Сдвиг от идеала: {clamped_menu_x - ideal_menu_x}px")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: ПРЕМИУМ АНИМАЦИЯ ПОЯВЛЕНИЯ МЕНЮ (iOS-like spring)
        # ═══════════════════════════════════════════════════════════════
        
        # Группа анимаций для одновременного воспроизведения
        anim_group = QtCore.QParallelAnimationGroup(menu)
        
        # 1. Анимация прозрачности (fade in)
        opacity_effect = QtWidgets.QGraphicsOpacityEffect(menu)
        menu.setGraphicsEffect(opacity_effect)
        opacity_effect.setOpacity(0.0)
        
        opacity_anim = QtCore.QPropertyAnimation(opacity_effect, b"opacity")
        opacity_anim.setDuration(380)  # 380ms - плавно и премиум
        opacity_anim.setStartValue(0.0)
        opacity_anim.setEndValue(1.0)
        opacity_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutExpo)  # Плавное замедление
        
        # 2. Анимация масштаба по вертикали (scaleY: 0.85 → 1)
        # Используем динамическое свойство для вертикального scale
        menu.setProperty("scale_y", 0.85)
        
        scale_anim = QtCore.QPropertyAnimation(menu, b"scale_y")
        scale_anim.setDuration(380)  # Синхронизировано
        scale_anim.setStartValue(0.85)
        scale_anim.setEndValue(1.0)
        scale_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)  # iOS-like spring
        
        # Подключаем обновление геометрии при изменении scale
        def update_menu_scale(value):
            try:
                # Получаем текущую геометрию
                if not hasattr(menu, '_original_height'):
                    menu._original_height = menu_height
                
                # Вычисляем новую высоту
                new_height = int(menu._original_height * value)
                
                # Обновляем позицию (anchor point внизу - в центре кнопки)
                new_y = button_global_pos.y() - new_height - 8
                
                # Устанавливаем новую геометрию
                menu.setGeometry(
                    menu_pos.x(),
                    new_y,
                    menu_width,
                    new_height
                )
            except RuntimeError:
                pass
        
        scale_anim.valueChanged.connect(update_menu_scale)
        
        # Добавляем анимации в группу
        anim_group.addAnimation(opacity_anim)
        anim_group.addAnimation(scale_anim)
        
        # Сохраняем ссылки для предотвращения garbage collection
        menu._anim_group = anim_group
        menu._opacity_effect = opacity_effect

        # ── Обработка действий через сигналы (нужно для popup()) ──
        def _do_search():
            self.use_search = not self.use_search
            if self.use_search:
                print("[MENU] ⚠️ FORCED SEARCH MODE активирован")
            else:
                print("[MENU] Режим 'Умный поиск'")

        search_action.triggered.connect(_do_search)
        file_action.triggered.connect(self.attach_file)
        if clear_action:
            clear_action.triggered.connect(self.clear_attached_file)

        # ── Анимация закрытия: screenshot-proxy паттерн ──
        _close_started = [False]

        def _animate_close():
            if _close_started[0]:
                return
            _close_started[0] = True

            cur_geo = menu.geometry()

            # grab() рендерит меню с его CSS (border-radius, прозрачность)
            try:
                px = menu.grab()
            except Exception:
                px = None

            # Proxy-виджет с прозрачным фоном поверх всего
            class _ProxyWidget(QtWidgets.QWidget):
                def __init__(self, pixmap, geo):
                    super().__init__(
                        None,
                        QtCore.Qt.WindowType.Tool |
                        QtCore.Qt.WindowType.FramelessWindowHint |
                        QtCore.Qt.WindowType.WindowStaysOnTopHint
                    )
                    self._px = pixmap
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
                    self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
                    self.setGeometry(geo)

                def paintEvent(self, event):
                    if self._px:
                        from PyQt6 import QtGui
                        p = QtGui.QPainter(self)
                        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                        p.drawPixmap(self.rect(), self._px)
                        p.end()

            proxy = _ProxyWidget(px, cur_geo)
            proxy.show()
            proxy.raise_()

            # Fade-out
            _c_eff = QtWidgets.QGraphicsOpacityEffect(proxy)
            proxy.setGraphicsEffect(_c_eff)
            _c_eff.setOpacity(1.0)

            _c_op = QtCore.QPropertyAnimation(_c_eff, b"opacity")
            _c_op.setDuration(180)
            _c_op.setStartValue(1.0)
            _c_op.setEndValue(0.0)
            _c_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            # Scale-down вниз
            end_geo = QtCore.QRect(
                cur_geo.x(),
                cur_geo.y() + int(cur_geo.height() * 0.12),
                cur_geo.width(),
                int(cur_geo.height() * 0.88)
            )
            _c_geo = QtCore.QPropertyAnimation(proxy, b"geometry")
            _c_geo.setDuration(180)
            _c_geo.setStartValue(cur_geo)
            _c_geo.setEndValue(end_geo)
            _c_geo.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            def _on_proxy_done():
                try:
                    proxy.close()
                except Exception:
                    pass
                self.attach_btn.clearFocus()
                self.input_field.setFocus()

            _c_op.finished.connect(_on_proxy_done)
            # Начинаем убирать blur ОДНОВРЕМЕННО с proxy-анимацией (не после неё)
            # чтобы overlay и proxy исчезали плавно вместе
            self._remove_menu_blur_effect()
            _c_op.start()
            _c_geo.start()
            proxy._anims = [_c_op, _c_geo, _c_eff]

        menu.aboutToHide.connect(_animate_close)

        # Запускаем анимацию появления и blur после небольшой задержки
        QtCore.QTimer.singleShot(120, anim_group.start)
        QtCore.QTimer.singleShot(120, self._apply_menu_blur_effect)

        # popup() — не блокирует event loop
        menu.popup(menu_pos)
    
    def _apply_menu_blur_effect(self):
        """Применить реальный blur эффект через снимок экрана"""
        print("[BLUR] Применяю blur эффект через снимок экрана")
        
        # ✅ Устанавливаем флаг что меню открыто
        self._menu_is_open = True
        
        # ✅ Сохраняем состояние кнопки "вниз" перед blur
        if hasattr(self, 'scroll_to_bottom_btn'):
            self._scroll_btn_was_visible = self.scroll_to_bottom_btn._is_visible_animated
        else:
            self._scroll_btn_was_visible = False
        
        # ═══════════════════════════════════════════════════════════════
        # 1. СОЗДАНИЕ РАЗМЫТОГО СНИМКА ЭКРАНА
        # ═══════════════════════════════════════════════════════════════
        
        # Создаем или переиспользуем overlay
        if not hasattr(self, '_blur_overlay'):
            self._blur_overlay = QtWidgets.QLabel(self)
            self._blur_overlay.setObjectName("blurOverlay")
            self._blur_overlay.setScaledContents(True)
            
            # Создаём opacity эффект для анимации появления
            self._overlay_opacity = QtWidgets.QGraphicsOpacityEffect(self._blur_overlay)
            self._blur_overlay.setGraphicsEffect(self._overlay_opacity)
            self._overlay_opacity.setOpacity(0.0)
        else:
            # Очищаем старый pixmap перед созданием нового
            self._blur_overlay.clear()
        
        # ШАГ 1: Делаем снимок экрана (скрываем overlay если он виден)
        self._blur_overlay.hide()
        QtWidgets.QApplication.processEvents()
        snapshot = self.grab()
        
        # ШАГ 2: Применяем blur к снимку
        # Создаем временный QLabel для применения blur effect
        temp_label = QtWidgets.QLabel()
        temp_label.setPixmap(snapshot)
        temp_label.resize(snapshot.size())
        
        # Применяем blur эффект
        blur_effect = QtWidgets.QGraphicsBlurEffect()
        blur_effect.setBlurRadius(15)  # Средний blur
        temp_label.setGraphicsEffect(blur_effect)
        
        # Рендерим размытый результат в новый pixmap
        blurred_pixmap = QtGui.QPixmap(snapshot.size())
        blurred_pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        
        painter = QtGui.QPainter(blurred_pixmap)
        temp_label.render(painter)
        painter.end()
        
        # Удаляем временный label
        temp_label.deleteLater()
        
        # ШАГ 3: Применяем затемнение поверх размытого снимка
        # Создаём полупрозрачный слой для затемнения
        overlay = QtGui.QPixmap(blurred_pixmap.size())
        is_dark = self.current_theme == "dark"
        
        if is_dark:
            overlay.fill(QtGui.QColor(0, 0, 0, 80))  # Легкое затемнение
        else:
            overlay.fill(QtGui.QColor(255, 255, 255, 80))  # Легкое осветление
        
        # Накладываем затемнение на размытый снимок
        final_painter = QtGui.QPainter(blurred_pixmap)
        final_painter.drawPixmap(0, 0, overlay)
        final_painter.end()
        
        # ШАГ 4: Устанавливаем размытый снимок в overlay
        self._blur_overlay.setPixmap(blurred_pixmap)
        self._blur_overlay.setGeometry(self.rect())
        self._blur_overlay.raise_()
        self._blur_overlay.show()
        
        # Анимация появления overlay
        if not hasattr(self, '_overlay_anim'):
            self._overlay_anim = QtCore.QPropertyAnimation(self._overlay_opacity, b"opacity")
        
        self._overlay_anim.stop()
        self._overlay_anim.setDuration(300)
        self._overlay_anim.setStartValue(0.0)
        self._overlay_anim.setEndValue(1.0)
        self._overlay_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._overlay_anim.start()
        
        # ═══════════════════════════════════════════════════════════════
        # 2. FADE OUT КНОПКИ "+"
        # ═══════════════════════════════════════════════════════════════
        # Создаём opacity эффект для кнопки (всегда свежий — старый мог быть удалён Qt)
        _btn_eff = QtWidgets.QGraphicsOpacityEffect(self.attach_btn)
        self.attach_btn.setGraphicsEffect(_btn_eff)
        self.attach_btn._opacity_effect = _btn_eff
        _btn_eff.setOpacity(1.0)
        
        # Анимируем opacity от 1.0 до 0.0
        self._button_fade_anim = QtCore.QPropertyAnimation(_btn_eff, b"opacity")
        self._button_fade_anim.setDuration(250)
        self._button_fade_anim.setStartValue(1.0)
        self._button_fade_anim.setEndValue(0.0)
        self._button_fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._button_fade_anim.start()
        
        # ═══════════════════════════════════════════════════════════════
        # 3. FADE OUT КНОПКИ "ВНИЗ" (используем её существующий opacity effect)
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, 'scroll_to_bottom_btn') and self.scroll_to_bottom_btn.isVisible():
            # Останавливаем текущую анимацию
            self.scroll_to_bottom_btn.fade_animation.stop()
            
            # Плавно скрываем кнопку
            self.scroll_to_bottom_btn.fade_animation.setDuration(250)
            self.scroll_to_bottom_btn.fade_animation.setStartValue(
                self.scroll_to_bottom_btn.opacity_effect.opacity()
            )
            self.scroll_to_bottom_btn.fade_animation.setEndValue(0.0)
            self.scroll_to_bottom_btn.fade_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            self.scroll_to_bottom_btn.fade_animation.start()
        
        print("[BLUR] Blur эффект применён, кнопка + скрыта")
    
    def _remove_menu_blur_effect(self):
        """Убрать overlay эффект и восстановить кнопку + при закрытии меню"""
        print("[BLUR] Убираю overlay эффект")
        
        # ✅ Устанавливаем флаг что меню закрыто
        self._menu_is_open = False
        
        # ═══════════════════════════════════════════════════════════════
        # 1. FADE OUT OVERLAY
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, '_overlay_anim') and hasattr(self, '_blur_overlay'):
            # Получаем текущее значение opacity
            current_opacity = self._overlay_opacity.opacity()
            
            self._overlay_anim.stop()
            self._overlay_anim.setDuration(250)
            self._overlay_anim.setStartValue(current_opacity)
            self._overlay_anim.setEndValue(0.0)
            self._overlay_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            
            # После завершения анимации - скрываем overlay
            def cleanup_overlay():
                # ✅ Проверяем что меню действительно закрыто
                if hasattr(self, '_menu_is_open') and self._menu_is_open:
                    print("[BLUR] Пропускаю cleanup - меню снова открыто")
                    return
                
                if hasattr(self, '_blur_overlay'):
                    self._blur_overlay.hide()
                    # Очищаем pixmap для освобождения памяти
                    self._blur_overlay.clear()
                    print("[BLUR] Overlay скрыт и очищен")
            
            # Отключаем предыдущие коллбэки
            try:
                self._overlay_anim.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            
            self._overlay_anim.finished.connect(cleanup_overlay)
            self._overlay_anim.start()
        
        # ═══════════════════════════════════════════════════════════════
        # 2. FADE IN КНОПКИ "+"
        # ═══════════════════════════════════════════════════════════════
        # ═══════════════════════════════════════════════════════════════
        # 2. FADE IN КНОПКИ «+» (восстанавливаем видимость)
        # ═══════════════════════════════════════════════════════════════
        try:
            eff = getattr(self.attach_btn, '_opacity_effect', None)
            if eff is not None:
                # Проверяем что C++ объект жив — вызов opacity() бросит RuntimeError если нет
                cur_op = eff.opacity()
                self._button_fade_anim.stop()
                self._button_fade_anim.setDuration(300)
                self._button_fade_anim.setStartValue(cur_op)
                self._button_fade_anim.setEndValue(1.0)
                self._button_fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                def _clear_btn_effect():
                    try:
                        self.attach_btn.setGraphicsEffect(None)
                    except Exception:
                        pass
                self._button_fade_anim.finished.connect(_clear_btn_effect)
                self._button_fade_anim.start()
            else:
                self.attach_btn.setGraphicsEffect(None)
        except (RuntimeError, Exception):
            # C++ объект удалён — просто сбрасываем эффект
            try:
                self.attach_btn.setGraphicsEffect(None)
            except Exception:
                pass
        
        # ═══════════════════════════════════════════════════════════════
        # 3. FADE IN КНОПКИ "ВНИЗ" (восстанавливаем если была видна до blur)
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, 'scroll_to_bottom_btn'):
            # Останавливаем текущую анимацию
            self.scroll_to_bottom_btn.fade_animation.stop()
            
            # ✅ ИСПРАВЛЕНИЕ: Используем сохраненное состояние
            if hasattr(self, '_scroll_btn_was_visible') and self._scroll_btn_was_visible:
                print("[BLUR] Восстанавливаю кнопку 'вниз' - она была видна до blur")
                # Плавно восстанавливаем видимость
                self.scroll_to_bottom_btn.fade_animation.setDuration(300)
                self.scroll_to_bottom_btn.fade_animation.setStartValue(
                    self.scroll_to_bottom_btn.opacity_effect.opacity()
                )
                self.scroll_to_bottom_btn.fade_animation.setEndValue(1.0)
                self.scroll_to_bottom_btn.fade_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
                self.scroll_to_bottom_btn.fade_animation.start()
            else:
                print("[BLUR] Кнопка 'вниз' не восстанавливается - она не была видна до blur")
        
        print("[BLUR] Кнопка + восстановлена")
    

    # ═══════════════════════════════════════════════════════════════
    # МЕТОДЫ УПРАВЛЕНИЯ ФАЙЛАМИ ЧАТОВ
    # ═══════════════════════════════════════════════════════════════
    
    def start_status_animation(self):
        """Запуск анимации точек в статусе"""
        self.status_dots_count = 0
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.timeout.connect(self.update_status_dots)
        self.status_timer.start(350)  # Интервал 350ms
    
    def update_status_dots(self):
        """Обновление точек в статусе"""
        # ✅ КРИТИЧНО: Проверка наличия status_base_text
        if not hasattr(self, 'status_base_text'):
            self.status_base_text = ""
        
        # ✅ КРИТИЧНО: Очищаем перед обновлением
        self.status_label.clear()
        
        dots = "." * self.status_dots_count
        self.status_label.setText(f"{self.status_base_text}{dots}")
        self.status_dots_count = (self.status_dots_count + 1) % 4  # 0, 1, 2, 3
    
    def stop_status_animation(self):
        """Остановка анимации точек"""
        if hasattr(self, 'status_timer') and self.status_timer.isActive():
            self.status_timer.stop()
        # ✅ КРИТИЧНО: Очищаем перед установкой пустой строки
        self.status_label.clear()
        self.status_label.setText("")

    def toggle_sidebar(self):
        """Переключение боковой панели с плавной анимацией (БЕЗ ДЁРГАНИЙ)"""
        current_width = self.sidebar.width()
        target_width = 280 if current_width == 0 else 0
        is_opening = target_width > 0
        
        # Скрываем панель удаления при закрытии sidebar
        if target_width == 0:
            self.hide_delete_panel()
        
        # ═══════════════════════════════════════════════════════════════
        # АНИМАЦИЯ SIDEBAR (плавное выдвижение/скрытие)
        # ═══════════════════════════════════════════════════════════════
        # Останавливаем предыдущие анимации если ещё идут
        if hasattr(self, 'animation') and self.animation:
            self.animation.stop()
        if hasattr(self, 'animation2') and self.animation2:
            self.animation2.stop()
        
        # Плавная анимация sidebar
        duration = 300   # ms
        easing = QtCore.QEasingCurve.Type.InOutQuad  # Плавная кривая
        
        self.animation = QtCore.QPropertyAnimation(self.sidebar, b"minimumWidth")
        self.animation.setDuration(duration)
        self.animation.setStartValue(current_width)
        self.animation.setEndValue(target_width)
        self.animation.setEasingCurve(easing)
        
        self.animation2 = QtCore.QPropertyAnimation(self.sidebar, b"maximumWidth")
        self.animation2.setDuration(duration)
        self.animation2.setStartValue(current_width)
        self.animation2.setEndValue(target_width)
        self.animation2.setEasingCurve(easing)
        
        self.animation.start()
        self.animation2.start()
        
        print(f"[SIDEBAR] {'Открываю' if is_opening else 'Закрываю'} sidebar с плавной анимацией")
    


    def manual_scroll_to_bottom(self):
        """
        Ручной скролл вниз при нажатии на кнопку с ПЛАВНОЙ анимацией.
        НЕ автоматический - только по клику пользователя.
        
        ОБНОВЛЕНИЕ LAYOUT:
        Когда пользователь нажимает кнопку "вниз", делаем полное
        обновление layout чтобы все накопленные сообщения отобразились корректно.
        
        ПЛАВНЫЙ СКРОЛЛ:
        Используем QPropertyAnimation для плавного скролла вниз.
        """
        print("[MANUAL_SCROLL] 🔄 Обновление layout перед скроллом вниз...")
        
        # Полное обновление layout для корректного отображения всех сообщений
        self.messages_layout.invalidate()
        self.messages_layout.activate()
        self.messages_widget.updateGeometry()
        # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: update() вместо repaint() + processEvents()
        self.scroll_area.viewport().update()
        
        # ═══════════════════════════════════════════════════════════════
        # ПЛАВНЫЙ СКРОЛЛ ВНИЗ
        # ═══════════════════════════════════════════════════════════════
        scrollbar = self.scroll_area.verticalScrollBar()
        
        # Создаём анимацию скролла
        if not hasattr(self, '_scroll_animation'):
            self._scroll_animation = QtCore.QPropertyAnimation(scrollbar, b"value")
        
        self._scroll_animation.stop()  # Останавливаем предыдущую если есть
        self._scroll_animation.setDuration(600)  # 600ms - более плавная и приятная анимация
        self._scroll_animation.setStartValue(scrollbar.value())
        self._scroll_animation.setEndValue(scrollbar.maximum())
        self._scroll_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutExpo)  # Более естественная кривая
        
        # Когда скролл завершится - плавно скрываем кнопку
        def on_scroll_finished():
            self.scroll_to_bottom_btn.smooth_hide()
        
        # Отключаем старый обработчик если был
        try:
            self._scroll_animation.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        
        self._scroll_animation.finished.connect(on_scroll_finished)
        self._scroll_animation.start()
        
        print("[MANUAL_SCROLL] ✓ Запущен плавный скролл вниз")
    
    def update_scroll_button_visibility(self):
        """
        Обновить видимость overlay-кнопки "вниз" на основе положения scrollBar.
        
        ═══ ПОЛНОСТЬЮ ПАССИВНЫЙ OVERLAY - АРХИТЕКТУРА ═══
        
        КРИТИЧНО - ПРАВИЛА ПАССИВНОСТИ:
        1. НЕ подключен к сигналам scrollbar (valueChanged, rangeChanged)
        2. Вызывается ТОЛЬКО явно:
           - После завершения layout в add_message_widget()
           - После ручного скролла в _update_button_after_scroll()
           - При resize окна в eventFilter
        3. ТОЛЬКО читает состояние scrollbar - НЕ изменяет его
        4. ТОЛЬКО меняет visibility (show/hide) - НЕ вызывает:
           - update(), repaint()
           - updateGeometry(), adjustSize()
           - invalidate(), activate() на любом layout
           - update_position() (позиция обновляется только в resize)
        
        ГАРАНТИИ:
        - НЕ влияет на layout сообщений
        - НЕ вызывает пересчёт геометрии
        - НЕ создаёт race condition с layout-pass
        - Layout уже завершён через adjustSize() до вызова этой функции
        
        ЛОГИКА:
        - ScrollBar внизу → hide()
        - ScrollBar не внизу → show()
        - Контент помещается → hide()
        """
        # Проверяем что мы на странице чата, а не настроек
        if hasattr(self, 'content_stack') and self.content_stack.currentIndex() != 0:
            self.scroll_to_bottom_btn.smooth_hide()
            return
        
        scrollbar = self.scroll_area.verticalScrollBar()
        
        # Проверяем что контент больше viewport
        if scrollbar.maximum() == 0:
            self.scroll_to_bottom_btn.smooth_hide()
            return
        
        # Показываем кнопку если НЕ внизу (с порогом 10px)
        if scrollbar.value() < scrollbar.maximum() - 10:
            # ПЛАВНОЕ ПОЯВЛЕНИЕ вместо резкого show()
            self.scroll_to_bottom_btn.smooth_show()
        else:
            # ПЛАВНОЕ ИСЧЕЗНОВЕНИЕ вместо резкого hide()
            self.scroll_to_bottom_btn.smooth_hide()
    
    def check_has_chats_with_messages(self) -> bool:
        """
        Проверить есть ли хоть один чат с сообщениями.
        Если все чаты пустые (или чатов вообще нет) — возвращает False.
        """
        try:
            import sqlite3 as _sq
            import chat_manager as _cm
            conn = _sq.connect(_cm.CHATS_DB)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM chat_messages")
            count = cur.fetchone()[0]
            conn.close()
            return count > 0
        except Exception as e:
            print(f"[CHECK_CHATS] Ошибка: {e}")
            return False

    def open_settings(self):
        """Открыть экран настроек"""
        print("[SETTINGS] Открытие настроек")
        
        # Скрываем кнопку скролла
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.scroll_to_bottom_btn.smooth_hide()
        
        # Скрываем ВСЕ элементы чата
        if hasattr(self, 'scroll_area'):
            self.scroll_area.hide()
        if hasattr(self, 'title_label'):
            self.title_label.hide()
        if hasattr(self, 'clear_btn'):
            self.clear_btn.hide()
        if hasattr(self, 'input_container'):
            self.input_container.hide()
        
        # Отключаем toggle_sidebar, подключаем close_settings
        if hasattr(self, 'menu_btn'):
            try:
                self.menu_btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.menu_btn.clicked.connect(self.close_settings)
        
        # Обновляем стили экрана настроек ПЕРЕД показом
        if hasattr(self, 'settings_view'):
            self.settings_view.apply_settings_styles()
            has_messages = self.check_has_chats_with_messages()
            self.settings_view.update_delete_all_btn_state(has_messages)
            
            # ═══════════════════════════════════════════════════════════════
            # ВАЖНО: Скрываем settings_view чтобы не было двойного появления
            # ═══════════════════════════════════════════════════════════════
            self.settings_view.hide()
        
        # Функция для показа настроек с анимацией (вызывается ПОСЛЕ переключения страницы)
        def show_settings_animated():
            print("[SETTINGS] Страница переключена, запускаю fade-in...")
            
            if not hasattr(self, 'settings_view'):
                return
            
            # Показываем виджет
            self.settings_view.show()
            
            # Применяем эффект opacity
            effect = QtWidgets.QGraphicsOpacityEffect(self.settings_view)
            self.settings_view.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            
            # Анимация появления
            anim = QtCore.QPropertyAnimation(effect, b"opacity")
            anim.setDuration(300)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            anim.start()
            
            # Сохраняем ссылку
            if not hasattr(self, '_settings_fade_animations'):
                self._settings_fade_animations = []
            self._settings_fade_animations.append(anim)
            
            print("[SETTINGS] ✓ Настройки плавно появляются")
        
        # Закрываем sidebar если открыт
        if self.sidebar.width() > 0:
            print("[SETTINGS] Закрываю sidebar...")
            self.toggle_sidebar()
            # Ждём закрытия sidebar + переключаем страницу + показываем с анимацией
            QtCore.QTimer.singleShot(400, lambda: [
                self.content_stack.setCurrentIndex(1),
                QtCore.QTimer.singleShot(50, show_settings_animated)
            ])
        else:
            print("[SETTINGS] Sidebar закрыт, открываю настройки")
            # Сразу переключаем страницу + показываем с анимацией
            self.content_stack.setCurrentIndex(1)
            QtCore.QTimer.singleShot(50, show_settings_animated)
        
        print(f"[SETTINGS] Текущий индекс: {self.content_stack.currentIndex()}")
    
        def switch_to_settings():
            print("[SETTINGS] ▶ switch_to_settings() вызвана")
            
            # Скрываем элементы header кроме кнопки меню
            if hasattr(self, 'title_label'):
                print("[SETTINGS] Скрываю title_label")
                self.title_label.hide()
            if hasattr(self, 'clear_btn'):
                print("[SETTINGS] Скрываю clear_btn")
                self.clear_btn.hide()
            
            # Скрываем footer (поле ввода, кнопки)
            if hasattr(self, 'input_container'):
                print("[SETTINGS] Скрываю input_container")
                self.input_container.hide()
            
            # Отключаем toggle_sidebar, подключаем close_settings
            if hasattr(self, 'menu_btn'):
                try:
                    self.menu_btn.clicked.disconnect()
                    print("[SETTINGS] Отключил старый обработчик menu_btn")
                except RuntimeError:
                    pass
                self.menu_btn.clicked.connect(self.close_settings)
                print("[SETTINGS] Подключил close_settings к menu_btn")
            
            # Плавный переход к настройкам
            print("[SETTINGS] Запускаю _animate_stack_transition(0 → 1)")
            self._animate_stack_transition(from_index=0, to_index=1, callback=None)
            print(f"[SETTINGS] ✓ Переключен на индекс: {self.content_stack.currentIndex()}")
        
        # Проверяем ширину sidebar
        sidebar_width = self.sidebar.width()
        print(f"[SETTINGS] Ширина sidebar: {sidebar_width}")
        
        # Если sidebar открыт - сначала закрываем его
        if sidebar_width > 0:
            print("[SETTINGS] Sidebar открыт, сначала закрываю его...")
            
            # Ждем завершения анимации закрытия sidebar
            def on_sidebar_closed():
                print("[SETTINGS] ✓ Sidebar закрыт (callback вызван)")
                # Небольшая задержка для плавности
                print("[SETTINGS] Задержка 100ms перед открытием настроек...")
                QtCore.QTimer.singleShot(100, switch_to_settings)
            
            # Подключаем callback к анимации
            if hasattr(self, 'animation') and self.animation:
                try:
                    self.animation.finished.disconnect()
                except (RuntimeError, TypeError):
                    pass
                self.animation.finished.connect(on_sidebar_closed)
                print("[SETTINGS] Callback подключен к анимации sidebar")
            else:
                print("[SETTINGS] ⚠️ animation не найдена!")
            
            print("[SETTINGS] Запускаю toggle_sidebar()")
            self.toggle_sidebar()
        else:
            print("[SETTINGS] Sidebar уже закрыт, сразу открываю настройки")
            switch_to_settings()
        
        print("[SETTINGS] ========================================")
        print("[SETTINGS] Открытие настроек - КОНЕЦ метода")
        print("[SETTINGS] ========================================")
    
        def switch_to_settings():
            # Скрываем элементы header кроме кнопки меню
            if hasattr(self, 'title_label'):
                self.title_label.hide()
            if hasattr(self, 'clear_btn'):
                self.clear_btn.hide()
            
            # Скрываем footer (поле ввода, кнопки)
            if hasattr(self, 'input_container'):
                self.input_container.hide()
            
            # Отключаем toggle_sidebar, подключаем close_settings
            if hasattr(self, 'menu_btn'):
                try:
                    self.menu_btn.clicked.disconnect()
                except (RuntimeError, TypeError):
                    pass
                self.menu_btn.clicked.connect(self.close_settings)
            
            # Плавный переход к настройкам
            self._animate_stack_transition(from_index=0, to_index=1, callback=None)
            print(f"[SETTINGS] Переключен на индекс: {self.content_stack.currentIndex()}")
        
        # Если sidebar открыт - сначала закрываем его
        if self.sidebar.width() > 0:
            print("[SETTINGS] Сначала закрываю sidebar...")
            # Ждем завершения анимации закрытия sidebar
            def on_sidebar_closed():
                print("[SETTINGS] Sidebar закрыт, переключаюсь на настройки...")
                # Небольшая задержка для плавности
                QtCore.QTimer.singleShot(100, switch_to_settings)
            
            # Подключаем callback к анимации
            if hasattr(self, 'animation') and self.animation:
                try:
                    self.animation.finished.disconnect()
                except (RuntimeError, TypeError):
                    pass
                self.animation.finished.connect(on_sidebar_closed)
            
            self.toggle_sidebar()
        else:
            # Sidebar уже закрыт, сразу переходим к настройкам
            switch_to_settings()
    
    def close_settings(self):
        """Закрыть настройки и вернуться к чату — с плавным fade-переходом"""
        print("[SETTINGS] Возврат к чату")
        self._animate_stack_transition(from_index=1, to_index=0, callback=self._after_close_settings)

    def _after_close_settings(self):
        """Вызывается после завершения анимации закрытия настроек"""
        print("[SETTINGS] Анимация завершена, показываю элементы интерфейса...")
        
        # ═══════════════════════════════════════════════════════════════
        # ИСПРАВЛЕНИЕ: Плавное появление элементов БЕЗ нарушения layout
        # ═══════════════════════════════════════════════════════════════
        
        # Восстанавливаем обработчик кнопки меню СРАЗУ
        if hasattr(self, 'menu_btn'):
            try:
                self.menu_btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.menu_btn.clicked.connect(self.toggle_sidebar)
        
        # Показываем все элементы БЕЗ анимации (чтобы layout правильно работал)
        if hasattr(self, 'scroll_area'):
            self.scroll_area.show()
        if hasattr(self, 'title_label'):
            self.title_label.show()
        if hasattr(self, 'clear_btn'):
            self.clear_btn.show()
        if hasattr(self, 'input_container'):
            self.input_container.show()
        
        # Обновляем layout ПЕРЕД анимацией
        QtWidgets.QApplication.processEvents()
        
        # Теперь применяем fade-in только к ВЕРХНЕМУ уровню виджетов
        widgets_to_animate = []
        
        if hasattr(self, 'scroll_area'):
            widgets_to_animate.append(self.scroll_area)
        if hasattr(self, 'title_label'):
            widgets_to_animate.append(self.title_label)
        if hasattr(self, 'clear_btn'):
            widgets_to_animate.append(self.clear_btn)
        # НЕ анимируем input_container - там сложный layout с кнопками
        # Вместо этого анимируем только внешний контейнер если он есть
        
        # Применяем эффект opacity ТОЛЬКО если это простые виджеты
        for widget in widgets_to_animate:
            # Проверяем что виджет видим
            if not widget.isVisible():
                continue
                
            effect = QtWidgets.QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            
            # Анимация появления
            anim = QtCore.QPropertyAnimation(effect, b"opacity")
            anim.setDuration(300)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
            
            # ВАЖНО: Убираем эффект после завершения анимации
            def remove_effect(w=widget):
                w.setGraphicsEffect(None)
                print(f"[SETTINGS] Убрал эффект с {w.objectName()}")
            
            anim.finished.connect(remove_effect)
            anim.start()
            
            # Сохраняем ссылку
            if not hasattr(self, '_fade_in_animations'):
                self._fade_in_animations = []
            self._fade_in_animations.append(anim)
        
        # input_container появляется БЕЗ анимации (чтобы не сломать layout)
        if hasattr(self, 'input_container'):
            self.input_container.show()
            print("[SETTINGS] input_container показан БЕЗ анимации (сохранён layout)")
        
        # Обновляем видимость кнопки скролла с задержкой
        QtCore.QTimer.singleShot(350, lambda: QtCore.QMetaObject.invokeMethod(
            self,
            "_update_button_after_scroll",
            QtCore.Qt.ConnectionType.QueuedConnection
        ))
        
        print("[SETTINGS] ✓ Элементы интерфейса плавно появляются")

    def _animate_stack_transition(self, from_index: int, to_index: int, callback=None):
        """
        Плавный fade-переход между страницами QStackedWidget.
        Делает скриншот текущей страницы, переключает, плавно убирает скриншот.
        """
        # Останавливаем предыдущую анимацию если идёт
        if hasattr(self, '_stack_anim') and self._stack_anim:
            try:
                self._stack_anim.stop()
                if hasattr(self, '_stack_overlay') and self._stack_overlay:
                    self._stack_overlay.deleteLater()
                    self._stack_overlay = None
            except RuntimeError:
                pass

        # Снимок текущего состояния (страницы from_index)
        snapshot = self.content_stack.grab()

        # Мгновенно переключаем страницу
        self.content_stack.setCurrentIndex(to_index)
        QtWidgets.QApplication.processEvents()

        # Накладываем снимок поверх нового содержимого
        overlay = QtWidgets.QLabel(self.content_stack)
        overlay.setPixmap(snapshot)
        overlay.setGeometry(0, 0, self.content_stack.width(), self.content_stack.height())
        overlay.setScaledContents(True)
        overlay.show()
        overlay.raise_()

        # Эффект прозрачности
        effect = QtWidgets.QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        effect.setOpacity(1.0)

        # Анимация: снимок плавно исчезает → видна новая страница
        anim = QtCore.QPropertyAnimation(effect, b"opacity")
        anim.setDuration(280)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)

        def on_finished():
            overlay.deleteLater()
            self._stack_overlay = None
            self._stack_anim = None
            if callback:
                callback()

        anim.finished.connect(on_finished)
        anim.start()

        self._stack_overlay = overlay
        self._stack_anim = anim
    
    def on_settings_applied(self, settings: dict):
        """Обработка применения настроек с плавной crossfade анимацией смены темы"""
        print(f"[SETTINGS] Применены настройки: {settings}")
        
        # Получаем параметры
        theme = settings.get("theme", "light")
        liquid_glass = settings.get("liquid_glass", True)
        
        # Проверяем, изменилась ли тема
        theme_changed = (self.current_theme != theme)
        glass_changed = (self.current_liquid_glass != liquid_glass)
        
        if theme_changed or glass_changed:
            # КРИТИЧНО: Останавливаем и очищаем предыдущую анимацию если она ещё идёт
            if hasattr(self, '_crossfade_group') and self._crossfade_group:
                self._crossfade_group.stop()
                self._crossfade_group.deleteLater()
                self._crossfade_group = None
            
            if hasattr(self, '_old_overlay') and self._old_overlay:
                self._old_overlay.deleteLater()
                self._old_overlay = None
            
            if hasattr(self, '_new_overlay') and self._new_overlay:
                self._new_overlay.deleteLater()
                self._new_overlay = None
            
            # ПЛАВНАЯ CROSSFADE АНИМАЦИЯ СМЕНЫ ТЕМЫ
            print(f"[SETTINGS] Запускаю crossfade анимацию: {self.current_theme} → {theme}")
            
            # ШАГ 1: Делаем скриншот СТАРОЙ темы
            old_pixmap = self.grab()
            
            # ШАГ 2: Применяем НОВУЮ тему (мгновенно, но скрыто под оверлеем)
            self.current_theme = theme
            self.current_liquid_glass = liquid_glass
            self.apply_styles(theme=theme, liquid_glass=liquid_glass)
            
            # Обновляем цвета файлового чипа при смене темы
            if hasattr(self, 'file_chip_container') and self.file_chip_container.isVisible():
                is_dark = (theme == 'dark')
                if is_dark:
                    self.file_chip.setStyleSheet("""
                        #fileChip {
                            background: rgba(102, 126, 234, 0.20);
                            border: 1px solid rgba(102, 126, 234, 0.40);
                            border-radius: 14px;
                            padding: 2px 6px;
                        }
                    """)
                    self.file_chip_label.setStyleSheet("color: #8fa3f5; background: transparent; border: none;")
                    self.file_chip_remove_btn.setStyleSheet("""
                        QPushButton {
                            background: rgba(102, 126, 234, 0.25);
                            color: #8fa3f5;
                            border: none;
                            border-radius: 11px;
                        }
                        QPushButton:hover {
                            background: rgba(239, 68, 68, 0.30);
                            color: #f87171;
                        }
                    """)
                else:
                    self.file_chip.setStyleSheet("""
                        #fileChip {
                            background: rgba(102, 126, 234, 0.15);
                            border: 1px solid rgba(102, 126, 234, 0.35);
                            border-radius: 14px;
                            padding: 2px 6px;
                        }
                    """)
                    self.file_chip_label.setStyleSheet("color: #667eea; background: transparent; border: none;")
                    self.file_chip_remove_btn.setStyleSheet("""
                        QPushButton {
                            background: rgba(102, 126, 234, 0.2);
                            color: #667eea;
                            border: none;
                            border-radius: 11px;
                        }
                        QPushButton:hover {
                            background: rgba(239, 68, 68, 0.25);
                            color: #ef4444;
                        }
                    """)
            
            # Обновляем стили всех существующих виджетов сообщений
            if hasattr(self, 'messages_layout'):
                for i in range(self.messages_layout.count()):
                    item = self.messages_layout.itemAt(i)
                    if item:
                        w = item.widget()
                        if w and hasattr(w, 'update_message_styles'):
                            try:
                                w.update_message_styles(theme, liquid_glass)
                            except RuntimeError:
                                pass

            # Обновляем стили кнопки "вниз"
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.scroll_to_bottom_btn.apply_theme_styles(theme=theme, liquid_glass=liquid_glass)
            
            # Обновляем стили настроек
            if hasattr(self, 'settings_view'):
                self.settings_view.apply_settings_styles()
            
            # Принудительно обновляем всё
            self.update()
            QtWidgets.QApplication.processEvents()
            
            # ШАГ 3: Делаем скриншот НОВОЙ темы
            new_pixmap = self.grab()
            
            # ШАГ 4: Создаём два оверлея для crossfade
            # Оверлей со старой темой (будет исчезать)
            old_overlay = QtWidgets.QLabel(self)
            old_overlay.setPixmap(old_pixmap)
            old_overlay.setGeometry(0, 0, self.width(), self.height())
            old_overlay.setScaledContents(True)
            old_overlay.show()
            old_overlay.raise_()
            
            # Оверлей с новой темой (будет проявляться)
            new_overlay = QtWidgets.QLabel(self)
            new_overlay.setPixmap(new_pixmap)
            new_overlay.setGeometry(0, 0, self.width(), self.height())
            new_overlay.setScaledContents(True)
            new_overlay.show()
            new_overlay.raise_()
            
            # Эффекты прозрачности
            old_effect = QtWidgets.QGraphicsOpacityEffect(old_overlay)
            old_overlay.setGraphicsEffect(old_effect)
            old_effect.setOpacity(1.0)
            
            new_effect = QtWidgets.QGraphicsOpacityEffect(new_overlay)
            new_overlay.setGraphicsEffect(new_effect)
            new_effect.setOpacity(0.0)
            
            # ШАГ 5: Анимация crossfade
            # Старая тема исчезает
            old_fade = QtCore.QPropertyAnimation(old_effect, b"opacity")
            old_fade.setDuration(400)  # 400ms
            old_fade.setStartValue(1.0)
            old_fade.setEndValue(0.0)
            old_fade.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
            
            # Новая тема появляется
            new_fade = QtCore.QPropertyAnimation(new_effect, b"opacity")
            new_fade.setDuration(400)  # 400ms
            new_fade.setStartValue(0.0)
            new_fade.setEndValue(1.0)
            new_fade.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
            
            # Группируем анимации для синхронного запуска
            animation_group = QtCore.QParallelAnimationGroup(self)
            animation_group.addAnimation(old_fade)
            animation_group.addAnimation(new_fade)
            
            def on_crossfade_finished():
                # Удаляем оверлеи
                old_overlay.deleteLater()
                new_overlay.deleteLater()
                print("[SETTINGS] ✓ Crossfade анимация завершена")
                
                # Очищаем ссылки
                self._old_overlay = None
                self._new_overlay = None
                self._crossfade_group = None
            
            animation_group.finished.connect(on_crossfade_finished)
            animation_group.start()
            
            # Сохраняем ссылки
            self._crossfade_group = animation_group
            self._old_overlay = old_overlay
            self._new_overlay = new_overlay
            
        else:
            # Если тема не изменилась, просто применяем стили без анимации
            self.current_theme = theme
            self.current_liquid_glass = liquid_glass
            
            self.apply_styles(theme=theme, liquid_glass=liquid_glass)
            
            # Обновляем стили всех существующих виджетов сообщений
            if hasattr(self, 'messages_layout'):
                for i in range(self.messages_layout.count()):
                    item = self.messages_layout.itemAt(i)
                    if item:
                        w = item.widget()
                        if w and hasattr(w, 'update_message_styles'):
                            try:
                                w.update_message_styles(theme, liquid_glass)
                            except RuntimeError:
                                pass

            # Обновляем стили кнопки "вниз"
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.scroll_to_bottom_btn.apply_theme_styles(theme=theme, liquid_glass=liquid_glass)
                print("[SETTINGS] ✓ Стили кнопки 'вниз' обновлены")
            
            # Обновляем стили настроек
            if hasattr(self, 'settings_view'):
                self.settings_view.apply_settings_styles()
        
        print("[SETTINGS] ✓ Стили успешно обновлены")


    def show_delete_panel(self, pos):
        """Показать контекстное меню при правом клике на чат"""
        item = self.chats_list.itemAt(pos)
        if not item:
            return
        
        chat_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Создаём контекстное меню
        context_menu = QtWidgets.QMenu(self)
        
        # Адаптивные стили в зависимости от темы
        if is_dark:
            context_menu.setStyleSheet("""
                QMenu {
                    background-color: rgba(30, 30, 35, 0.85);
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 12px;
                    padding: 6px;
                }
                QMenu::item {
                    padding: 10px 20px;
                    border-radius: 8px;
                    color: #e0e0e0;
                }
                QMenu::item:selected {
                    background-color: rgba(220, 38, 38, 0.25);
                    color: #ff6b6b;
                }
            """)
        else:
            context_menu.setStyleSheet("""
                QMenu {
                    background-color: rgba(255, 255, 255, 0.72);
                    border: 1px solid rgba(255, 255, 255, 0.85);
                    border-radius: 12px;
                    padding: 6px;
                }
                QMenu::item {
                    padding: 10px 20px;
                    border-radius: 8px;
                    color: #2d3748;
                }
                QMenu::item:selected {
                    background-color: rgba(239, 68, 68, 0.15);
                    color: #dc2626;
                }
            """)
        
        # Пункт "Удалить чат"
        delete_action = context_menu.addAction("🗑️ Удалить чат")
        
        # Показываем меню и обрабатываем выбор
        action = context_menu.exec(self.chats_list.mapToGlobal(pos))
        
        if action == delete_action:
            self.delete_chat_by_id(chat_id)

    def hide_delete_panel(self):
        """Скрыть панель удаления"""
        if self.delete_panel.width() == 0:
            return
        
        anim1 = QtCore.QPropertyAnimation(self.delete_panel, b"minimumWidth")
        anim1.setDuration(200)
        anim1.setStartValue(self.delete_panel.width())
        anim1.setEndValue(0)
        anim1.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        
        anim2 = QtCore.QPropertyAnimation(self.delete_panel, b"maximumWidth")
        anim2.setDuration(200)
        anim2.setStartValue(self.delete_panel.width())
        anim2.setEndValue(0)
        anim2.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        
        anim1.start()
        anim2.start()

    def delete_chat_by_id(self, chat_id: int):
        """Удалить чат по ID"""
        # Подтверждение удаления
        reply = QtWidgets.QMessageBox.question(
            self, "Удаление чата",
            "Вы уверены, что хотите удалить этот чат?\nВсе сообщения будут удалены.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # Если удаляем активный чат
            if chat_id == self.current_chat_id:
                # Создаём новый пустой чат
                new_chat_id = self.chat_manager.create_chat("Новый чат")
                self.chat_manager.set_active_chat(new_chat_id)
                self.current_chat_id = new_chat_id
                if _DS_MEMORY is not None:
                    _DS_MEMORY.on_chat_switch(new_chat_id)
            
            # Удаляем контекстную память чата ПЕРЕД удалением самого чата
            try:
                from context_memory_manager import ContextMemoryManager
                ContextMemoryManager().delete_chat_context(chat_id)
                print(f"[DELETE_CHAT] ✓ Контекстная память LLaMA чата {chat_id} удалена")
            except Exception as e:
                print(f"[DELETE_CHAT] ⚠️ Ошибка удаления контекстной памяти: {e}")
            try:
                if DeepSeekMemoryManager is not None:
                    _DS_MEMORY.delete_chat_context(chat_id)
                    print(f"[DELETE_CHAT] ✓ Память DeepSeek чата {chat_id} удалена")
            except Exception as e:
                print(f"[DELETE_CHAT] ⚠️ Ошибка удаления памяти DeepSeek: {e}")

            # Удаляем чат
            self.chat_manager.delete_chat(chat_id)
            
            # Обновляем список
            self.load_chats_list()
            self.load_current_chat()

    def delete_selected_chat(self):
        """Удалить выбранный чат (для кнопки в панели)"""
        if not self.chat_to_delete:
            return
        
        self.delete_chat_by_id(self.chat_to_delete)
        
        # Скрываем панель удаления
        self.hide_delete_panel()
        self.chat_to_delete = None

    def _cleanup_empty_chats_on_startup(self):
        """Удалить все старые чаты без пользовательских сообщений при запуске"""
        try:
            all_chats = self.chat_manager.get_all_chats()
            deleted_count = 0
            
            for chat in all_chats:
                chat_id = chat['id']
                # Получаем сообщения чата
                messages = self.chat_manager.get_chat_messages(chat_id, limit=100)
                
                # Проверяем есть ли хотя бы одно сообщение от пользователя
                has_user_messages = any(msg[0] == "user" for msg in messages)
                
                if not has_user_messages:
                    # Удаляем пустой чат и его контекстную память
                    print(f"[CLEANUP] Удаляю пустой чат ID={chat_id}, title='{chat['title']}'")
                    try:
                        from context_memory_manager import ContextMemoryManager
                        ContextMemoryManager().delete_chat_context(chat_id)
                    except Exception:
                        pass
                    try:
                        if DeepSeekMemoryManager is not None:
                            _DS_MEMORY.delete_chat_context(chat_id)
                    except Exception:
                        pass
                    self.chat_manager.delete_chat(chat_id)
                    deleted_count += 1
                else:
                    print(f"[CLEANUP] Сохраняю чат ID={chat_id} - есть сообщения пользователя")
            
            if deleted_count > 0:
                print(f"[CLEANUP] ✓ Удалено пустых чатов: {deleted_count}")
            else:
                print(f"[CLEANUP] ✓ Пустых чатов не найдено")
                
        except Exception as e:
            print(f"[CLEANUP] ✗ Ошибка при очистке: {e}")
            import traceback
            traceback.print_exc()
    
    def load_chats_list(self):
        """Загрузить список чатов"""
        self.chats_list.clear()
        chats = self.chat_manager.get_all_chats()
        
        for chat in chats:
            item = QtWidgets.QListWidgetItem(chat['title'])
            item.setData(QtCore.Qt.ItemDataRole.UserRole, chat['id'])
            self.chats_list.addItem(item)
            
            if chat['is_active']:
                self.chats_list.setCurrentItem(item)

    def load_current_chat(self):
        """Загрузить текущий активный чат (УЛУЧШЕНО: загрузка файлов)"""
        if not self.current_chat_id:
            return
        
        print(f"[LOAD_CURRENT] ════════════════════════════════════════")
        print(f"[LOAD_CURRENT] Загрузка чата ID={self.current_chat_id}")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: ОЧИСТКА ФАЙЛОВ ИЗ ПРЕДЫДУЩЕГО ЧАТА
        # ═══════════════════════════════════════════════════════════════
        if self.attached_files:
            print(f"[LOAD_CURRENT] 🗑️ Очищаем {len(self.attached_files)} старых файлов")
            self.attached_files = []
            self.update_file_chips()
        
        # ✅ КРИТИЧНО: Полностью очищаем все виджеты сообщений
        # Структура layout: [message1, message2, ..., stretch(1)]
        # Удаляем только виджеты сообщений, оставляем stretch в конце
        items_to_remove = []
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                # Удаляем все виджеты сообщений (они имеют атрибут speaker)
                if hasattr(widget, 'speaker'):
                    items_to_remove.append(widget)
        
        # Удаляем собранные виджеты
        for widget in items_to_remove:
            self.messages_layout.removeWidget(widget)
            widget.deleteLater()
        
        print(f"[LOAD_CURRENT] Удалено виджетов: {len(items_to_remove)}")
        
        # Загружаем сообщения текущего чата (оптимизировано: 30 вместо 50)
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=30)
        
        # Проверяем состояние кнопки "Очистить"
        self.clear_btn.setEnabled(True)
        self.clear_btn.setStyleSheet("")
        
        # Показываем приветствие если чат пустой
        if len(messages) == 0:
            welcome_msg = "Привет! Готов к работе."
            self.add_message_widget("Система", welcome_msg, add_controls=False)
            print(f"[LOAD_CURRENT] ✅ Загрузка завершена (пустой чат)")
            print(f"[LOAD_CURRENT] ════════════════════════════════════════")
            return
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ЗАГРУЗКА ФАЙЛОВ ОТКЛЮЧЕНА
        # ═══════════════════════════════════════════════════════════════
        # ИСПРАВЛЕНИЕ: НЕ загружаем файлы в поле прикрепления
        # Файлы сохраняются только для контекста AI (через memory)
        # но НЕ отображаются пользователю как прикреплённые
        print(f"[LOAD_CURRENT] ℹ️ Загрузка файлов в UI отключена (файлы в памяти AI)")
        
        # Определяем какие сообщения показывать с анимацией (последние 2 для ускорения)
        total_messages = len(messages)
        
        # Загружаем существующие сообщения с файлами
        for idx, msg_data in enumerate(messages):
            role    = msg_data[0]
            content           = msg_data[1]
            files             = msg_data[2] if len(msg_data) > 2 else None
            sources           = msg_data[3] if len(msg_data) > 3 else []
            # speaker_name сохранён в БД — используем его, иначе текущий ИИ
            stored_speaker    = msg_data[5] if len(msg_data) > 5 else None
            stored_regen_hist = msg_data[6] if len(msg_data) > 6 else None
            
            if role == "user":
                speaker = "Вы"
            else:
                speaker = stored_speaker if stored_speaker else llama_handler.ASSISTANT_NAME
            if role not in ["user", "assistant"]:
                continue
            
            # Проверяем, входит ли сообщение в последние 2 (оптимизировано)
            is_recent = (total_messages - idx) <= 2
            
            # Создаём виджет с файлами и источниками
            message_widget = MessageWidget(
                speaker, content, add_controls=True,
                language=self.current_language,
                main_window=self,
                parent=self.messages_widget,
                thinking_time=0,
                attached_files=files,
                sources=sources or []
            )
            
            # Восстанавливаем историю перегенерации из БД
            if role == "assistant" and stored_regen_hist and len(stored_regen_hist) >= 1:
                try:
                    message_widget._regen_history = stored_regen_hist
                    message_widget._regen_idx = len(stored_regen_hist) - 1
                    # Инициализируем _regen_nav_group если его нет (старые виджеты)
                    if not hasattr(message_widget, '_regen_nav_group'):
                        message_widget._regen_nav_group = None
                    message_widget._regen_apply_entry(message_widget._regen_idx)
                    print(f"[LOAD_CHAT] ✓ Восстановлена история: {len(stored_regen_hist)} вариантов")
                except Exception as e:
                    print(f"[LOAD_CHAT] ⚠️ Ошибка восстановления истории: {e}")

            # Для старых сообщений сразу убираем анимацию
            if not is_recent:
                if hasattr(message_widget, 'opacity_effect'):
                    message_widget.opacity_effect.setOpacity(1.0)
                # Отключаем анимации появления
                if hasattr(message_widget, 'fade_in_animation'):
                    message_widget.fade_in_animation.stop()
                if hasattr(message_widget, 'pos_animation'):
                    message_widget.pos_animation.stop()
            else:
                # Для последних 2 - анимация включена по умолчанию (оптимизировано)
                pass
            
            # Добавляем в layout (stretch уже удалён, добавляем в конец)
            self.messages_layout.addWidget(message_widget)
            
            # Запускаем анимацию для последних 2 сообщений (оптимизировано)
            if is_recent and not IS_WINDOWS and hasattr(message_widget, '_start_appear_animation'):
                # Запускаем с плавной задержкой для красивого каскадного эффекта (150ms между сообщениями)
                # Увеличена задержка под новую 800ms анимацию
                QtCore.QTimer.singleShot(60 + idx * 150, message_widget._start_appear_animation)
        
        # ═══════════════════════════════════════════════════════════════
        # АВТОМАТИЧЕСКИЙ СКРОЛЛ ВНИЗ ПОСЛЕ ЗАГРУЗКИ ЧАТА
        # ═══════════════════════════════════════════════════════════════
        # Полное обновление layout (invalidate гарантирует пересчёт ВСЕГО дерева)
        self.messages_layout.invalidate()
        self.messages_layout.activate()
        self.messages_widget.updateGeometry()
        # ✅ processEvents убран — используем delayed scroll через QTimer
        
        # Скроллим вниз с задержкой 350ms:
        # - последние 2 сообщения запускают анимацию в 60ms и 210ms
        # - 350ms гарантирует что layout успел пересчитать размеры ДО скролла
        def scroll_to_bottom_delayed():
            # Повторный invalidate + activate — layout ГАРАНТИРОВАННО завершён
            self.messages_layout.invalidate()
            self.messages_layout.activate()
            self.messages_widget.updateGeometry()
            # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: убрали processEvents() — он вызывал
            # принудительную синхронную перерисовку всего окна включая нижнюю панель
            scrollbar = self.scroll_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            # Обновляем видимость кнопки "вниз"
            if hasattr(self, 'scroll_to_bottom_btn'):
                self.update_scroll_button_visibility()
        
        QtCore.QTimer.singleShot(350, scroll_to_bottom_delayed)
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: УПРАВЛЕНИЕ ВИДИМОСТЬЮ КНОПОК РЕГЕНЕРАЦИИ И РЕДАКТИРОВАНИЯ
        # ═══════════════════════════════════════════════════════════════
        # Показываем кнопки только у последних сообщений
        def manage_regenerate_buttons():
            # Находим последнее сообщение ассистента
            last_assistant_widget = None
            # Находим последнее сообщение пользователя
            last_user_widget = None
            
            # Проходим в обратном порядке чтобы найти последние сообщения
            for i in range(self.messages_layout.count() - 1, -1, -1):
                item = self.messages_layout.itemAt(i)
                if item and item.widget() and hasattr(item.widget(), 'speaker'):
                    widget = item.widget()
                    
                    # Ищем последнее сообщение ассистента (не "Вы" и не "Система")
                    if last_assistant_widget is None and widget.speaker not in ["Вы", "Система"]:
                        last_assistant_widget = widget
                    
                    # Ищем последнее сообщение пользователя
                    if last_user_widget is None and widget.speaker == "Вы":
                        last_user_widget = widget
                    
                    # Если нашли оба - можно остановиться
                    if last_assistant_widget and last_user_widget:
                        break
            
            # Скрываем все кнопки регенерации у сообщений ассистента
            # Показываем только у последнего
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item and item.widget() and hasattr(item.widget(), 'speaker'):
                    widget = item.widget()
                    
                    # Управление кнопкой регенерации (у сообщений ассистента)
                    if widget.speaker not in ["Вы", "Система"]:
                        if hasattr(widget, 'regenerate_button') and widget.regenerate_button:
                            if widget == last_assistant_widget:
                                widget.regenerate_button.setVisible(True)
                            else:
                                widget.regenerate_button.setVisible(False)
                    
                    # Управление кнопкой редактирования (у сообщений пользователя)
                    if widget.speaker == "Вы":
                        if hasattr(widget, 'edit_button') and widget.edit_button:
                            if widget == last_user_widget:
                                widget.edit_button.setVisible(True)
                            else:
                                widget.edit_button.setVisible(False)
            
            print(f"[LOAD_CURRENT] ✓ Управление кнопками завершено")
        
        # Запускаем управление кнопками с небольшой задержкой после загрузки
        QtCore.QTimer.singleShot(400, manage_regenerate_buttons)

    # ─── Просмотрщики файлов (вызываются из attachment_manager через self) ───

    def _show_image_viewer(self, file_path: str):
        """Мини-просмотрщик изображений внутри приложения."""
        viewer = _ImageViewerDialog(file_path, parent=self)
        viewer.exec()

    def _show_text_viewer(self, file_path: str):
        """Мини-просмотрщик текстовых файлов внутри приложения."""
        viewer = _TextViewerDialog(file_path, parent=self)
        viewer.exec()

    def _preview_file(self, file_path: str):
        """Открывает предпросмотр файла в зависимости от типа."""
        if not os.path.exists(file_path):
            from PyQt6 import QtWidgets
            QtWidgets.QMessageBox.warning(
                self, "Файл не найден",
                f"Файл не найден:\n{file_path}\n\nВозможно, файл был перемещён.",
                QtWidgets.QMessageBox.StandardButton.Ok
            )
            return
        if is_image_file(file_path):
            self._show_image_viewer(file_path)
        elif is_text_file(file_path):
            self._show_text_viewer(file_path)
        else:
            # Открываем в системном приложении
            import subprocess, sys
            try:
                if sys.platform == 'darwin':
                    subprocess.run(['open', file_path], check=True)
                elif sys.platform == 'win32':
                    os.startfile(file_path)
                else:
                    subprocess.run(['xdg-open', file_path], check=True)
            except Exception as e:
                from PyQt6 import QtWidgets
                QtWidgets.QMessageBox.warning(
                    self, "Ошибка", f"Не удалось открыть файл:\n{e}",
                    QtWidgets.QMessageBox.StandardButton.Ok
                )


    def create_new_chat(self):
        """Создать новый чат (УЛУЧШЕНО: с плавной анимацией кнопки)"""
        
        # ═══════════════════════════════════════════════════════════════
        # АНИМАЦИЯ КНОПКИ "+ Новый чат" (bounce эффект)
        # ═══════════════════════════════════════════════════════════════
        # Находим кнопку нового чата
        new_chat_btn = None
        for i in range(self.sidebar.layout().count()):
            widget = self.sidebar.layout().itemAt(i).widget()
            if widget and isinstance(widget, QtWidgets.QPushButton):
                if "Новый чат" in widget.text() or widget.text() == "+ Новый чат":
                    new_chat_btn = widget
                    break
        
        if new_chat_btn:
            # Создаём анимацию масштабирования
            if not hasattr(self, '_new_chat_btn_press_anim'):
                self._new_chat_btn_press_anim = QtCore.QPropertyAnimation(new_chat_btn, b"geometry")
            
            original_geo = new_chat_btn.geometry()
            center_x = original_geo.center().x()
            center_y = original_geo.center().y()
            
            # Уменьшаем до 0.92 scale для более тонкого эффекта
            scale_factor = 0.92
            new_width = int(original_geo.width() * scale_factor)
            new_height = int(original_geo.height() * scale_factor)
            pressed_geo = QtCore.QRect(
                center_x - new_width // 2,
                center_y - new_height // 2,
                new_width,
                new_height
            )
            
            # Быстрое нажатие
            self._new_chat_btn_press_anim.stop()
            self._new_chat_btn_press_anim.setDuration(100)
            self._new_chat_btn_press_anim.setStartValue(original_geo)
            self._new_chat_btn_press_anim.setEndValue(pressed_geo)
            self._new_chat_btn_press_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutQuad)
            
            # После нажатия - возврат с bounce
            def on_new_chat_press_finished():
                if not hasattr(self, '_new_chat_btn_release_anim'):
                    self._new_chat_btn_release_anim = QtCore.QPropertyAnimation(new_chat_btn, b"geometry")
                
                self._new_chat_btn_release_anim.setDuration(350)
                self._new_chat_btn_release_anim.setStartValue(pressed_geo)
                self._new_chat_btn_release_anim.setEndValue(original_geo)
                # OutBack создаёт лёгкий spring bounce эффект
                self._new_chat_btn_release_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
                self._new_chat_btn_release_anim.start()
            
            try:
                self._new_chat_btn_press_anim.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._new_chat_btn_press_anim.finished.connect(on_new_chat_press_finished)
            self._new_chat_btn_press_anim.start()
            
            print("[NEW_CHAT] ✨ Запущена анимация кнопки нового чата")
        
        # ═══════════════════════════════════════════════════════════════
        # ЛОГИКА ОЧИСТКИ ПУСТЫХ ЧАТОВ
        # ═══════════════════════════════════════════════════════════════
        # Проверяем текущий чат - если он пустой, удаляем его перед созданием нового
        if self.current_chat_id:
            messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=10)
            user_messages = [msg for msg in messages if msg[0] == "user"]
            
            # Если в текущем чате нет сообщений пользователя - удаляем его
            if len(user_messages) == 0:
                print(f"[NEW_CHAT] Удаляем пустой чат {self.current_chat_id} перед созданием нового")
                try:
                    from context_memory_manager import ContextMemoryManager
                    ContextMemoryManager().delete_chat_context(self.current_chat_id)
                except Exception:
                    pass
                try:
                    if DeepSeekMemoryManager is not None:
                        _DS_MEMORY.delete_chat_context(self.current_chat_id)
                except Exception:
                    pass
                    self.chat_manager.delete_chat(self.current_chat_id)
                except Exception as e:
                    print(f"[NEW_CHAT] Ошибка удаления пустого чата: {e}")
        
        # Создаём новый чат
        chat_id = self.chat_manager.create_chat("Новый чат")
        self.chat_manager.set_active_chat(chat_id)
        self.current_chat_id = chat_id
        if _DS_MEMORY is not None:
            _DS_MEMORY.on_chat_switch(chat_id)
        
        # Обновляем флаги стартового чата
        self.startup_chat_id = chat_id
        self.startup_chat_has_messages = False
        
        self.load_chats_list()
        
        # Принудительно скрываем кнопку "вниз" ДО загрузки чата, чтобы
        # add_message_widget внутри load_current_chat не успел её показать снова
        if hasattr(self, 'scroll_to_bottom_btn'):
            btn = self.scroll_to_bottom_btn
            btn.fade_animation.stop()
            btn.opacity_effect.setOpacity(0.0)
            btn.hide()
            btn._is_visible_animated = False
        
        self.load_current_chat()
        
        # Закрываем sidebar после создания с небольшой задержкой для анимации
        QtCore.QTimer.singleShot(150, self.toggle_sidebar)
        
        print(f"[NEW_CHAT] ✓ Создан новый чат ID={chat_id}")

    def switch_chat(self, item):
        """Переключить чат с полной остановкой генерации (УЛУЧШЕНО: очистка файлов)"""
        chat_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        
        print(f"[SWITCH_CHAT] ════════════════════════════════════════")
        print(f"[SWITCH_CHAT] Переключение с чата {self.current_chat_id} на {chat_id}")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: ПОЛНАЯ ОСТАНОВКА ГЕНЕРАЦИИ (КРИТИЧНО!)
        # ═══════════════════════════════════════════════════════════════
        if self.is_generating:
            print(f"[SWITCH_CHAT] ⚠️ Останавливаем активную генерацию перед переключением")
            
            # Останавливаем флаг генерации
            self.is_generating = False
            
            # Отменяем воркер
            if hasattr(self, 'current_worker'):
                self.current_worker = None
            
            # Останавливаем анимацию статуса
            if hasattr(self, 'stop_status_animation'):
                self.stop_status_animation()
            
            # Очищаем статус
            self.status_label.setText("")
            
            # Сбрасываем UI
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.send_btn.setText("→")
            
            print(f"[SWITCH_CHAT] ✓ Генерация остановлена")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ОЧИСТКА ПРИКРЕПЛЁННЫХ ФАЙЛОВ ИЗ СТАРОГО ЧАТА
        # ═══════════════════════════════════════════════════════════════
        if self.attached_files:
            print(f"[SWITCH_CHAT] 🗑️ Очищаем {len(self.attached_files)} файлов из старого чата")
            self.attached_files = []
            self.update_file_chips()
        
        # ═══ ЛОГИКА ОЧИСТКИ ПУСТЫХ ЧАТОВ ═══
        # Если переключаемся с пустого чата - удаляем его
        if self.current_chat_id and chat_id != self.current_chat_id:
            messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=10)
            user_messages = [msg for msg in messages if msg[0] == "user"]
            
            # Если в текущем чате нет сообщений пользователя - удаляем его
            if len(user_messages) == 0:
                print(f"[SWITCH_CHAT] Удаляем пустой чат {self.current_chat_id} при переключении")
                try:
                    from context_memory_manager import ContextMemoryManager
                    ContextMemoryManager().delete_chat_context(self.current_chat_id)
                except Exception:
                    pass
                try:
                    if DeepSeekMemoryManager is not None:
                        _DS_MEMORY.delete_chat_context(self.current_chat_id)
                except Exception:
                    pass
                try:
                    self.chat_manager.delete_chat(self.current_chat_id)
                except Exception as e:
                    print(f"[SWITCH_CHAT] Ошибка удаления пустого чата: {e}")
        
        # ✅ GUARD: Очищаем поле ввода при переключении
        try:
            self.input_field.clear()
        except Exception:
            pass
        
        self.chat_manager.set_active_chat(chat_id)
        self.current_chat_id = chat_id
        if _DS_MEMORY is not None:
            _DS_MEMORY.on_chat_switch(chat_id)
        
        # Обновляем флаги стартового чата
        self.startup_chat_id = None
        self.startup_chat_has_messages = False
        
        self.load_chats_list()
        self.load_current_chat()
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: ЗАГРУЗКА ФАЙЛОВ ОТКЛЮЧЕНА
        # ═══════════════════════════════════════════════════════════════
        # ИСПРАВЛЕНИЕ: НЕ загружаем файлы в поле прикрепления
        # Файлы сохраняются только для контекста AI (через memory)
        print(f"[SWITCH_CHAT] ℹ️ Загрузка файлов в UI отключена")
        
        print(f"[SWITCH_CHAT] ✅ Переключение завершено")
        print(f"[SWITCH_CHAT] ════════════════════════════════════════")
        
        # Закрываем sidebar после переключения
        self.toggle_sidebar()
    def add_message_widget(self, speaker: str, text: str, add_controls: bool = False, thinking_time: float = 0, action_history: list = None, attached_files: list = None, sources: list = None, is_acknowledgment: bool = False):
        """
        Добавить виджет сообщения в layout БЕЗ АВТОСКРОЛЛА.
        
        УМНОЕ ОБНОВЛЕНИЕ В ЗАВИСИМОСТИ ОТ ПОЗИЦИИ ПОЛЬЗОВАТЕЛЯ:
        ════════════════════════════════════════════════════════════
        
        ЛОГИКА:
        • Пользователь ВНИЗУ → Обновляем layout с периодической синхронизацией
        • Пользователь НЕ внизу (читает историю) → МИНИМАЛЬНОЕ обновление
        
        МИНИМАЛЬНОЕ ОБНОВЛЕНИЕ (когда пользователь читает историю):
        ✓ Добавляем виджет в layout (addWidget)
        ✓ Показываем виджет (show)
        ✓ НЕ обновляем viewport (чтобы не мешать чтению)
        ✓ НЕ вызываем processEvents (избегаем "застревания")
        ✓ Пузыри не мешают скроллу
        
        ПЕРИОДИЧЕСКАЯ СИНХРОНИЗАЦИЯ (когда пользователь внизу):
        ✓ Каждое 5-е сообщение → полное обновление
        ✓ Остальные → быстрое обновление
        ✓ Viewport обновляется корректно
        
        РЕЗУЛЬТАТ:
        • Когда читаешь историю → новые сообщения НЕ мешают
        • Когда внизу → всё обновляется нормально
        • БЕЗ автоскролла
        • БЕЗ "застревания" пузырей
        ════════════════════════════════════════════════════════════
        """
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: СОХРАНЯЕМ ТЕКУЩУЮ ПОЗИЦИЮ СКРОЛЛА
        # ═══════════════════════════════════════════════════════════════
        scrollbar = self.scroll_area.verticalScrollBar()
        old_value = scrollbar.value()
        old_max = scrollbar.maximum()
        was_at_bottom = (old_max == 0) or (old_value >= old_max - 10)
        
        # ═══════════════════════════════════════════════════════════════
        # ПОДСЧЁТ КОЛИЧЕСТВА СООБЩЕНИЙ
        # ═══════════════════════════════════════════════════════════════
        message_count = 0
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item and item.widget() and hasattr(item.widget(), 'speaker'):
                message_count += 1
        
        # ═══════════════════════════════════════════════════════════════
        # ОПРЕДЕЛЯЕМ РЕЖИМ ОБНОВЛЕНИЯ
        # ═══════════════════════════════════════════════════════════════
        FULL_UPDATE_INTERVAL = 5
        is_full_update = (message_count % FULL_UPDATE_INTERVAL == 0)
        
        # Создаём виджет
        message_widget = MessageWidget(
            speaker, text, add_controls,
            language=self.current_language,
            main_window=self,
            parent=self.messages_widget,
            thinking_time=thinking_time,
            action_history=action_history,
            attached_files=attached_files,
            sources=sources or [],
            is_acknowledgment=is_acknowledgment
        )
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ДОБАВЛЕНИЕ В LAYOUT
        # ═══════════════════════════════════════════════════════════════
        self.messages_layout.addWidget(message_widget)
        message_widget.show()
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: ОБНОВЛЕНИЕ LAYOUT (ЗАВИСИТ ОТ ПОЗИЦИИ ПОЛЬЗОВАТЕЛЯ)
        # ═══════════════════════════════════════════════════════════════
        
        if not was_at_bottom:
            # ──────────────────────────────────────────────────────────
            # ПОЛЬЗОВАТЕЛЬ ЧИТАЕТ ИСТОРИЮ (НЕ внизу)
            # ──────────────────────────────────────────────────────────
            # МИНИМАЛЬНОЕ обновление - только добавили виджет
            # НЕ трогаем viewport чтобы не мешать чтению
            print(f"[ADD_MESSAGE] 📖 Минимальное обновление (пользователь читает историю)")
            
            # НЕ вызываем activate/update/processEvents
            # Виджет добавлен в layout, но viewport не обновляется
            # Когда пользователь вернётся вниз - всё обновится
            
        else:
            # ──────────────────────────────────────────────────────────
            # ПОЛЬЗОВАТЕЛЬ ВНИЗУ (видит новые сообщения)
            # ──────────────────────────────────────────────────────────
            # Периодическая синхронизация
            
            if is_full_update:
                print(f"[ADD_MESSAGE] 🔄 ПОЛНОЕ обновление (сообщение #{message_count + 1})")
                
                # ПОЛНОЕ обновление с синхронизацией
                self.messages_layout.invalidate()
                self.messages_layout.activate()
                self.messages_widget.updateGeometry()
                
                # ✅ ИСПРАВЛЕНИЕ ДЁРГАНЬЯ: используем update() вместо repaint() + processEvents()
                # repaint() + processEvents() вызывали перерисовку всего окна включая нижнюю панель
                self.scroll_area.viewport().update()
                
            else:
                print(f"[ADD_MESSAGE] ⚡ БЫСТРОЕ обновление (сообщение #{message_count + 1})")
                
                # БЫСТРОЕ обновление без processEvents
                self.messages_layout.activate()
                self.messages_widget.updateGeometry()
                self.scroll_area.viewport().update()
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 4: ВОССТАНАВЛИВАЕМ ПОЗИЦИЮ СКРОЛЛА (БЕЗ АВТОСКРОЛЛА)
        # ═══════════════════════════════════════════════════════════════
        if old_max > 0 and not was_at_bottom:
            # Если пользователь НЕ был внизу - сохраняем его позицию
            scrollbar.setValue(old_value)
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 5: ОБНОВЛЯЕМ КНОПКУ "ВНИЗ"
        # ═══════════════════════════════════════════════════════════════
        if hasattr(self, 'scroll_to_bottom_btn'):
            self.update_scroll_button_visibility()
        
        # Анимация появления (не влияет на layout)
        if not IS_WINDOWS and hasattr(message_widget, '_start_appear_animation'):
            QtCore.QMetaObject.invokeMethod(
                message_widget,
                "_start_appear_animation",
                QtCore.Qt.ConnectionType.QueuedConnection
            )
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 6: УПРАВЛЕНИЕ ВИДИМОСТЬЮ КНОПОК РЕГЕНЕРАЦИИ И РЕДАКТИРОВАНИЯ
        # ═══════════════════════════════════════════════════════════════
        # Показываем кнопку регенерации только у последнего сообщения ассистента
        # Показываем кнопку редактирования только у последнего сообщения пользователя
        if speaker != "Система":
            # Отложенное управление кнопками через 100ms (минимальная задержка)
            def manage_buttons():
                # РЕГЕНЕРАЦИЯ: Скрываем у всех ответов ИИ кроме последнего
                if speaker != "Вы":
                    for i in range(self.messages_layout.count()):
                        item = self.messages_layout.itemAt(i)
                        if item and item.widget() and hasattr(item.widget(), 'speaker'):
                            widget = item.widget()
                            # Проверяем что это сообщение ассистента
                            if widget.speaker != "Вы" and widget.speaker != "Система":
                                # Если это не текущий виджет - скрываем кнопку
                                if widget != message_widget and hasattr(widget, 'regenerate_button') and widget.regenerate_button:
                                    widget.regenerate_button.setVisible(False)
                                # Если это текущий виджет - показываем кнопку
                                elif widget == message_widget and hasattr(widget, 'regenerate_button') and widget.regenerate_button:
                                    widget.regenerate_button.setVisible(True)
                
                # РЕДАКТИРОВАНИЕ: Скрываем у всех сообщений пользователя кроме последнего
                else:  # speaker == "Вы"
                    for i in range(self.messages_layout.count()):
                        item = self.messages_layout.itemAt(i)
                        if item and item.widget() and hasattr(item.widget(), 'speaker'):
                            widget = item.widget()
                            # Проверяем что это сообщение пользователя
                            if widget.speaker == "Вы":
                                # Если это не текущий виджет - скрываем кнопку редактирования
                                if widget != message_widget and hasattr(widget, 'edit_button') and widget.edit_button:
                                    widget.edit_button.setVisible(False)
                                # Если это текущий виджет - показываем кнопку редактирования
                                elif widget == message_widget and hasattr(widget, 'edit_button') and widget.edit_button:
                                    widget.edit_button.setVisible(True)
                
                print(f"[ADD_MESSAGE] ✓ Управление кнопками завершено")
            
            # Запускаем управление кнопками отложенно
            QtCore.QTimer.singleShot(100, manage_buttons)
    
    def send_message(self):
        """Отправка сообщения пользователя
        
        ВАЖНО: Всегда берёт текст ТОЛЬКО из поля ввода (self.input_field.text())
        Никогда не использует старые значения или данные из других чатов
        """
        
        # Если идёт генерация - останавливаем и возвращаем текст в поле
        if self.is_generating:
            print(f"[SEND] ═══════════════════════════════════════════")
            print(f"[SEND] ОСТАНОВКА ГЕНЕРАЦИИ")
            
            self.is_generating = False
            
            # Помечаем текущий worker как отменённый
            if hasattr(self, 'current_worker') and self.current_worker:
                self.current_worker._cancelled = True
                print(f"[SEND] ✓ Worker помечен как отменённый")
            
            self.current_worker = None
            
            # Останавливаем анимацию статуса
            if hasattr(self, 'stop_status_animation'):
                self.stop_status_animation()
            
            # ── Удаляем последнее сообщение пользователя из БД и UI ──
            # Оно было сохранено при отправке, но ответа не последовало —
            # без удаления AI увидит его в истории и ответит на него повторно.
            
            # ✅ ВОССТАНОВЛЕНИЕ: Сохраняем текст и файлы ПЕРЕД удалением виджета
            restored_text = ""
            restored_files = []
            
            try:
                conn = sqlite3.connect("chats.db")
                cur = conn.cursor()
                cur.execute("""
                    SELECT role, content FROM chat_messages
                    WHERE chat_id = ?
                    ORDER BY id DESC LIMIT 1
                """, (self.current_chat_id,))
                last = cur.fetchone()
                if last and last[0] == "user":
                    restored_text = last[1] or ""
                    cur.execute("""
                        DELETE FROM chat_messages
                        WHERE chat_id = ? AND id = (
                            SELECT id FROM chat_messages
                            WHERE chat_id = ?
                            ORDER BY id DESC LIMIT 1
                        )
                    """, (self.current_chat_id, self.current_chat_id))
                    conn.commit()
                    print("[SEND] ✓ Незавершённое сообщение пользователя удалено из БД")
                conn.close()
            except Exception as e:
                print(f"[SEND] ⚠️ Ошибка удаления сообщения из БД: {e}")

            # ✅ ВОССТАНОВЛЕНИЕ: Забираем прикреплённые файлы из последнего виджета ДО его удаления
            try:
                for i in range(self.messages_layout.count() - 1, -1, -1):
                    item = self.messages_layout.itemAt(i)
                    if item and item.widget() and hasattr(item.widget(), 'speaker'):
                        w = item.widget()
                        if w.speaker == "Вы":
                            # Забираем файлы из виджета если они там есть
                            if hasattr(w, 'attached_files') and w.attached_files:
                                restored_files = list(w.attached_files)
                            self.messages_layout.removeWidget(w)
                            w.deleteLater()
                            print("[SEND] ✓ Виджет сообщения пользователя удалён из UI")
                            break
            except Exception as e:
                print(f"[SEND] ⚠️ Ошибка удаления виджета: {e}")
            
            # Если из виджета файлы не получили — берём сохранённую копию
            if not restored_files and hasattr(self, '_last_sent_files') and self._last_sent_files:
                restored_files = list(self._last_sent_files)
            # Если текст из БД не получили — берём сохранённую копию
            if not restored_text and hasattr(self, '_last_sent_text') and self._last_sent_text:
                restored_text = self._last_sent_text

            # ✅ ВОССТАНОВЛЕНИЕ: Возвращаем текст в поле ввода
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.send_btn.setText("→")
            
            if restored_text:
                self.input_field.setText(restored_text)
                self.input_field.setCursorPosition(len(restored_text))
                print(f"[SEND] ✓ Текст возвращён в поле ввода: '{restored_text[:40]}...'")
            
            # ✅ ВОССТАНОВЛЕНИЕ: Возвращаем прикреплённые файлы
            if restored_files:
                try:
                    self.attached_files = restored_files
                    self.update_file_chips()
                    print(f"[SEND] ✓ Восстановлено {len(restored_files)} прикреплённых файлов")
                except Exception as e:
                    print(f"[SEND] ⚠️ Не удалось восстановить файлы: {e}")
            
            # Очищаем статус сразу (без задержки)
            self.status_label.setText("")
            
            print(f"[SEND] ✅ Генерация остановлена, текст и файлы возвращены")
            print(f"[SEND] ═══════════════════════════════════════════")
            return
        
        global CURRENT_LANGUAGE
        # ИСТОЧНИК ИСТИНЫ - текст из поля ввода
        user_text = self.input_field.text().strip()
        if not user_text:
            return
        
        print(f"[SEND] Отправка сообщения: {user_text[:50]}...")
        
        # Проверка орфографии убрана - нейросеть сама переспросит если не поймёт
        # ════════════════════════════════════════════════════════════════
        # ИСПРАВЛЕНИЕ №3: Проверка на короткие подтверждения
        # ════════════════════════════════════════════════════════════════
        is_acknowledgment, acknowledgment_response = is_short_acknowledgment(user_text)
        if is_acknowledgment:
            print(f"[SEND] Обнаружено короткое подтверждение: {user_text} → {acknowledgment_response}")
            
            # Добавляем сообщение пользователя
            self.input_field.clear()
            self.add_message_widget("Вы", user_text, add_controls=True)
            self.chat_manager.save_message(self.current_chat_id, "user", user_text)
            
            # Отвечаем немедленно без вызова AI
            self.add_message_widget(llama_handler.ASSISTANT_NAME, acknowledgment_response, add_controls=True, is_acknowledgment=True)
            self.chat_manager.save_message(self.current_chat_id, "assistant", acknowledgment_response, speaker_name=llama_handler.ASSISTANT_NAME)
            
            # Обновляем название чата если это первое сообщение
            try:
                messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=5)
                if messages and len(messages) == 2:
                    first_user_msg = messages[0][1] if len(messages[0]) > 1 and messages[0][0] == "user" else ""
                    if first_user_msg and isinstance(first_user_msg, str) and len(first_user_msg) > 0:
                        chat_title = first_user_msg[:40]
                        if len(first_user_msg) > 40:
                            chat_title += "..."
                        chat_title = chat_title[0].upper() + chat_title[1:] if len(chat_title) > 0 else "Новый чат"
                        self.chat_manager.update_chat_title(self.current_chat_id, chat_title)
                        self.load_chats_list()
            except Exception as e:
                print(f"[SEND] Ошибка обновления названия чата: {e}")
            
            return  # Завершаем метод, не вызывая AI
        # ════════════════════════════════════════════════════════════════



        should_forget = detect_forget_command(user_text)
        if should_forget:
            print("[SEND] Обнаружена команда забыть!")
            
            # Добавляем сообщение пользователя в чат
            self.input_field.clear()
            self.add_message_widget("Вы", user_text, add_controls=True)
            self.chat_manager.save_message(self.current_chat_id, "user", user_text)
            
            # Извлекаем цель забывания
            forget_info = extract_forget_target(user_text)
            
            if forget_info["forget_all"]:
                # ПОЛНАЯ ОЧИСТКА
                print("[SEND] Выполняю полную очистку памяти...")
                
                # Очищаем сообщения чата
                self.chat_manager.clear_chat_messages(self.current_chat_id)
                
                # Очищаем контекстную память (LLaMA и DeepSeek)
                try:
                    from context_memory_manager import ContextMemoryManager
                    context_mgr = ContextMemoryManager()
                    context_mgr.clear_context_memory(self.current_chat_id)
                    print(f"[SEND] ✓ Контекстная память LLaMA очищена для chat_id={self.current_chat_id}")
                except Exception as e:
                    print(f"[SEND] ✗ Ошибка очистки контекстной памяти: {e}")
                try:
                    if DeepSeekMemoryManager is not None:
                        _DS_MEMORY.clear_context_memory(self.current_chat_id)
                        print(f"[SEND] ✓ Память DeepSeek очищена для chat_id={self.current_chat_id}")
                except Exception as e:
                    print(f"[SEND] ✗ Ошибка очистки памяти DeepSeek: {e}")
                
                # Сбрасываем название на "Новый чат"
                self.chat_manager.update_chat_title(self.current_chat_id, "Новый чат")
                
                # Обновляем список чатов
                self.load_chats_list()
                
                # Ответ от имени AI (а не системы!)
                if self.current_language == "russian":
                    ai_response = "Хорошо, я забыл! 😊"
                else:
                    ai_response = "Okay, I've forgotten! 😊"
                
            else:
                # СЕЛЕКТИВНОЕ УДАЛЕНИЕ
                target = forget_info["target"]
                print(f"[SEND] Выполняю селективное удаление: '{target}'")
                
                try:
                    from context_memory_manager import ContextMemoryManager
                    context_mgr = ContextMemoryManager()
                    
                    # Выполняем селективное удаление
                    result = selective_forget_memory(
                        self.current_chat_id, 
                        target, 
                        context_mgr, 
                        self.chat_manager
                    )
                    
                    if result["success"]:
                        print(f"[SEND] ✓ {result['message']}")
                        
                        # Обновляем список чатов
                        self.load_chats_list()
                        
                        # Формируем ответ в зависимости от результата
                        if result["deleted_count"] > 0:
                            if self.current_language == "russian":
                                ai_response = f"✓ Готово! Я забыл информацию о '{target}'. {result['message']}"
                            else:
                                ai_response = f"✓ Done! I've forgotten information about '{target}'. {result['message']}"
                        else:
                            if self.current_language == "russian":
                                ai_response = f"Я не нашёл упоминаний '{target}' в нашей истории. Возможно, мы не обсуждали это."
                            else:
                                ai_response = f"I couldn't find any mentions of '{target}' in our history. Perhaps we didn't discuss this."
                    else:
                        if self.current_language == "russian":
                            ai_response = f"❌ Произошла ошибка при удалении: {result['message']}"
                        else:
                            ai_response = f"❌ An error occurred during deletion: {result['message']}"
                        
                except Exception as e:
                    print(f"[SEND] ✗ Ошибка селективного удаления: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    if self.current_language == "russian":
                        ai_response = f"❌ Не удалось забыть '{target}': {e}"
                    else:
                        ai_response = f"❌ Failed to forget '{target}': {e}"
            
            self.add_message_widget(llama_handler.ASSISTANT_NAME, ai_response, add_controls=False)
            self.chat_manager.save_message(self.current_chat_id, "assistant", ai_response, speaker_name=llama_handler.ASSISTANT_NAME)
            return

        language_switch = detect_language_switch(user_text)
        if language_switch and language_switch != CURRENT_LANGUAGE:
            CURRENT_LANGUAGE = language_switch
            self.current_language = language_switch

            if language_switch == "english":
                notification = "✓ Language switched to English"
            else:
                notification = "✓ Язык изменён на русский"

            self.add_message_widget("Система", notification, add_controls=False)

        self.current_user_message = user_text
        
        # ✅ ВОССТАНОВЛЕНИЕ ПРИ ОТМЕНЕ: сохраняем текст и файлы ДО очистки поля
        self._last_sent_text = user_text
        self._last_sent_files = list(self.attached_files) if self.attached_files else []
        
        # ═══════════════════════════════════════════════════════════
        # УМНАЯ АДАПТИВНАЯ СИСТЕМА ВЕБ-ПОИСКА
        # ═══════════════════════════════════════════════════════════
        
        # DeepSeek: веб-поиск полностью отключён
        if llama_handler.CURRENT_AI_MODEL_KEY == "deepseek":
            print("[SEND] ✗ Веб-поиск ОТКЛЮЧЁН для DeepSeek")
            actual_use_search = False
        # ═══════════════════════════════════════════════════════════
        # ВАЖНО: Если есть прикреплённые файлы - НЕ использовать веб-поиск!
        # ═══════════════════════════════════════════════════════════
        elif self.attached_files:
            print(f"[SEND] 📎 Обнаружены прикреплённые файлы ({len(self.attached_files)})")
            print("[SEND] ✗ Веб-поиск ОТКЛЮЧЁН (есть файлы для анализа)")
            actual_use_search = False
        else:
            # Получаем историю чата для контекстного анализа
            chat_history = self.chat_manager.get_chat_messages(self.current_chat_id, limit=5)
            
            # Анализируем намерение пользователя с учётом контекста
            intent_result = analyze_intent_for_search(user_text, forced_search=self.use_search, chat_history=chat_history)
            
            # ПРИОРИТЕТ: Принудительный поиск переопределяет всё
            if intent_result["forced"]:
                print("[SEND] 🔴 FORCED SEARCH MODE - поиск обязателен (пользователь нажал кнопку)")
                actual_use_search = True
            elif intent_result["requires_search"]:
                print(f"[SEND] ✓ Автоматический поиск активирован (уверенность: {intent_result['confidence']:.2f})")
                print(f"[SEND] Причина: {intent_result['reason']}")
                actual_use_search = True
                # НЕ сохраняем self.use_search = True - это должен делать только пользователь!
            else:
                print("[SEND] ✗ Поиск не требуется")
                actual_use_search = False  # Явно отключаем поиск
        
        # Адаптируем deep_thinking в зависимости от режима AI
        if self.ai_mode == AI_MODE_FAST:
            actual_deep_thinking = False
        elif self.ai_mode == AI_MODE_THINKING:
            actual_deep_thinking = True
        elif self.ai_mode == AI_MODE_PRO:
            actual_deep_thinking = True  # В режиме "Про" всегда используем углублённое мышление
        else:
            actual_deep_thinking = self.deep_thinking  # Fallback на старое значение
        
        print(f"[SEND] Режим AI: {self.ai_mode}")
        print(f"[SEND] Deep thinking: {actual_deep_thinking}")
        print(f"[SEND] Search enabled: {actual_use_search}")
        
        # Сохраняем текущие режимы для восстановления при редактировании
        self.last_message_deep_thinking = self.deep_thinking
        self.last_message_use_search = actual_use_search
        
        # ═══════════════════════════════════════════════════════════════════════════
        # СОХРАНЕНИЕ ПАРАМЕТРОВ ДЛЯ PIPELINE
        # ═══════════════════════════════════════════════════════════════════════════
        # Сохраняем параметры для использования в pipeline
        self.current_ai_mode = self.ai_mode
        self.current_use_search = actual_use_search
        self.current_deep_thinking = actual_deep_thinking
        
        # Проверяем режим редактирования
        # Проверяем режим редактирования
        if not self.is_editing:
            # Обычная отправка - добавляем сообщение
            self.input_field.clear()
            
            # Плавно удаляем системное приветствие если это первое сообщение
            if self.messages_layout.count() == 2:  # Только stretch + приветствие
                first_widget = self.messages_layout.itemAt(0).widget()
                if first_widget and hasattr(first_widget, 'speaker') and first_widget.speaker == "Система":
                    # Запускаем fade-out для приветствия
                    first_widget.fade_out_and_delete()
                    print("[SEND] Системное приветствие плавно удаляется")
            
            self.add_message_widget("Вы", user_text, add_controls=True,
                                     attached_files=list(self.attached_files) if self.attached_files else None)
            
            # Сохраняем сообщение с файлами в БД (полный путь, чтобы можно было открыть позже)
            files_to_save = list(self.attached_files) if self.attached_files else None
            self.chat_manager.save_message(self.current_chat_id, "user", user_text, files_to_save)
            
            # Сохраняем список файлов в контекстную память (для AI)
            if self.attached_files:
                try:
                    _current_model = llama_handler.CURRENT_AI_MODEL_KEY
                    context_mgr = get_memory_manager(_current_model)
                    files_list = [os.path.basename(f) for f in self.attached_files]
                    files_info = f"📎 Файлы к сообщению '{user_text[:30]}...': {', '.join(files_list)}"
                    context_mgr.save_context_memory(self.current_chat_id, "message_files", files_info)
                    print(f"[SEND] ✓ Сохранена информация о {len(files_list)} файлах")
                except Exception as e:
                    print(f"[SEND] ⚠️ Ошибка сохранения информации о файлах: {e}")
            
            # ═══ ЛОГИКА СТАРТОВОГО ЧАТА ═══
            # Если это стартовый чат и первое сообщение - помечаем что он больше не пустой
            if hasattr(self, 'startup_chat_id') and self.current_chat_id == self.startup_chat_id:
                self.startup_chat_has_messages = True
                print(f"[STARTUP_CHAT] Стартовый чат {self.startup_chat_id} теперь содержит сообщения")
            
            # ═══════════════════════════════════════════════════════════════════════════
            # ЗАПУСК ПОЭТАПНОГО STATUS PIPELINE В НИЖНЕМ ЛЕВОМ УГЛУ
            # ═══════════════════════════════════════════════════════════════════════════
            # ЭТАП 1: Обработка запроса (немедленно)
            # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
            self.status_label.clear()
            self.status_label.setText("обрабатываю запрос…")
            print(f"[STATUS_PIPELINE] Этап 1: обрабатываю запрос…")
            
            # ЭТАП 2: Анализ (через 300ms)
            QtCore.QTimer.singleShot(300, lambda: self._status_pipeline_analyzing())
            
            print("[SEND] Новое сообщение добавлено")
        else:
            # Режим редактирования - НЕ добавляем сообщение, оно уже было удалено
            self.input_field.clear()
            self.add_message_widget("Вы", user_text, add_controls=True,
                                     attached_files=list(self.attached_files) if self.attached_files else None)
            
            # Сохраняем сообщение с файлами в БД (полный путь для открытия)
            files_to_save = list(self.attached_files) if self.attached_files else None
            self.chat_manager.save_message(self.current_chat_id, "user", user_text, files_to_save)
            
            # Сохраняем список файлов в контекстную память (для AI)
            if self.attached_files:
                try:
                    _current_model = llama_handler.CURRENT_AI_MODEL_KEY
                    context_mgr = get_memory_manager(_current_model)
                    files_list = [os.path.basename(f) for f in self.attached_files]
                    files_info = f"📎 Файлы к сообщению '{user_text[:30]}...': {', '.join(files_list)}"
                    context_mgr.save_context_memory(self.current_chat_id, "message_files", files_info)
                    print(f"[SEND] ✓ Сохранена информация о {len(files_list)} файлах (редактирование)")
                except Exception as e:
                    print(f"[SEND] ⚠️ Ошибка сохранения информации о файлах: {e}")
            
            # Запуск pipeline при регенерации
            # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
            self.status_label.clear()
            self.status_label.setText("обрабатываю запрос…")
            print(f"[STATUS_PIPELINE] Регенерация - Этап 1: обрабатываю запрос…")
            QtCore.QTimer.singleShot(300, lambda: self._status_pipeline_analyzing())
            
            # Сбрасываем флаг редактирования
            self.is_editing = False
            self.editing_message_text = ""
            print("[SEND] Отредактированное сообщение отправлено")

        self.input_field.setEnabled(False)
        self.send_btn.setText("⏸")
        self.send_btn.setEnabled(True)
        self.is_generating = True

        # ═══════════════════════════════════════════════════════════
        # ДВУХФАЗНЫЙ РЕЖИМ ОТВЕТА
        # ═══════════════════════════════════════════════════════════
        
        # ФАЗА 1: Быстрый предварительный ответ (если НЕ используется поиск)
        if not actual_use_search and not self.deep_thinking:
            print("[SEND] 📝 ФАЗА 1: Предоставляем быстрый ответ без поиска")
        # Запускаем анимацию точек
        self.start_status_animation()
        
        # Запускаем таймер обдумывания
        self.thinking_start_time = time.time()

        # Запускаем воркер с ПРАВИЛЬНЫМИ флагами и режимом AI
        worker = AIWorker(user_text, self.current_language, actual_deep_thinking, actual_use_search, False, self.chat_manager, self.current_chat_id, self.attached_files, self.ai_mode)
        worker.signals.finished.connect(self.handle_response)
        self.current_worker = worker  # Сохраняем ссылку на текущего воркера
        self._current_request_id = worker.request_id  # Запоминаем ID запроса
        
        # ✅ ИСПРАВЛЕНИЕ: Сохраняем worker в список для предотвращения удаления signals
        self.active_workers.append(worker)
        # Очищаем список от завершённых workers (максимум 5)
        if len(self.active_workers) > 5:
            self.active_workers = self.active_workers[-5:]
        
        self.threadpool.start(worker)
        print(f"[SEND] Запущен воркер генерации (search={actual_use_search}, deep={actual_deep_thinking}, mode={self.ai_mode})")
        
        # Очищаем прикреплённые файлы после отправки
        if self.attached_files:
            print(f"[SEND] Файлы отправлены в модель: {', '.join([os.path.basename(f) for f in self.attached_files])}")
            self.clear_attached_file()  # Очищаем все файлы

    def handle_response(self, response: str, sources: list = None):
        """Обработка ответа AI с полной защитой от ошибок (УЛУЧШЕНО: проверка отмены)"""
        try:
            # ✅ GUARD 1: СТРОГАЯ проверка - игнорируем сообщения для другого чата
            # Это предотвращает появление "чужих" сообщений при переключении чатов
            if hasattr(self, 'current_worker'):
                # Если воркер был отменён (current_worker = None), игнорируем его ответ
                if self.current_worker is None:
                    print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем ответ отменённого воркера (current_worker = None)")
                    return
                
                # ✅ GUARD 1.5: Проверяем флаг отмены в worker
                if hasattr(self.current_worker, '_cancelled') and self.current_worker._cancelled:
                    print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем ответ отменённого воркера (флаг _cancelled = True)")
                    return
                # ✅ GUARD 1.6: Проверяем совпадение request_id (защита от "призраков")
                if hasattr(self, '_current_request_id') and hasattr(self.current_worker, 'request_id'):
                    if self.current_worker.request_id != self._current_request_id:
                        print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем устаревший запрос (id несовпадение)")
                        return
                
                # ✅ GUARD 2: Проверяем что воркер принадлежит текущему чату
                if hasattr(self.current_worker, 'chat_id') and self.current_worker.chat_id != self.current_chat_id:
                    print(f"[HANDLE_RESPONSE] ⚠️ Игнорируем ответ от другого чата (воркер chat_id={self.current_worker.chat_id}, текущий={self.current_chat_id})")
                    return
            
            # ВАЖНО: Сбрасываем флаг генерации
            self.is_generating = False
            
            # Вычисляем время обдумывания с защитой
            thinking_time_to_show = 0
            try:
                if hasattr(self, 'thinking_start_time') and self.thinking_start_time:
                    self.thinking_elapsed_time = time.time() - self.thinking_start_time
                    print(f"[THINKING] Время обдумывания: {self.thinking_elapsed_time:.2f}s")
                    # Передаём время если был режим "думающий", "про" или "поиск"
                    show_timer = (self.ai_mode in [AI_MODE_THINKING, AI_MODE_PRO]) or self.use_search
                    thinking_time_to_show = self.thinking_elapsed_time if show_timer else 0
                else:
                    self.thinking_elapsed_time = 0
            except Exception as e:
                print(f"[HANDLE_RESPONSE] Ошибка расчёта времени: {e}")
                self.thinking_elapsed_time = 0
            
            # ═══════════════════════════════════════════════════════════════════════════
            # ✅ УНИВЕРСАЛЬНЫЙ ФИЛЬТР ТЕХНИЧЕСКИХ ОШИБОК
            # ═══════════════════════════════════════════════════════════════════════════
            
            # Проверка 1: Пустой или None ответ
            if not response or response is None:
                print(f"[ERROR_FILTER] ✗ Получен пустой ответ (None или пустая строка)")
                # НЕ создаём сообщение, полностью игнорируем
                return
            
            # Проверка 2: Не строка
            if not isinstance(response, str):
                print(f"[ERROR_FILTER] ✗ Ответ не является строкой: {type(response)}")
                # НЕ создаём сообщение
                return
            
            # Проверка 3: Признаки технических ошибок (только явные системные ошибки Python)
            error_indicators = [
                "Traceback (most recent call last)",
                "object is not iterable",
            ]
            
            error_prefixes = [
                "[Ошибка]",
                "File \"",
            ]
            
            # Проверяем содержимое на технические ошибки
            response_lower = response.lower()
            has_error = False
            
            for indicator in error_indicators:
                if indicator in response or indicator.lower() in response_lower:
                    print(f"[ERROR_FILTER] ✗ Обнаружен индикатор ошибки: {indicator}")
                    has_error = True
                    break
            
            # Проверяем начало строки
            if not has_error:
                for prefix in error_prefixes:
                    if response.startswith(prefix):
                        print(f"[ERROR_FILTER] ✗ Ответ начинается с: {prefix}")
                        has_error = True
                        break
            
            # Если обнаружена техническая ошибка
            if has_error:
                print(f"[ERROR_FILTER] ✗ Техническая ошибка обнаружена, показываем нейтральное сообщение")
                print(f"[ERROR_FILTER] Оригинальный ответ (логируется): {response[:200]}...")
                
                # Заменяем на нейтральное сообщение
                if self.current_language == "russian":
                    response = "Не удалось обработать запрос. Попробуйте ещё раз."
                else:
                    response = "Failed to process request. Please try again."
            
            # ═══════════════════════════════════════════════════════════════════════════
            
            # Проверяем валидность ответа (дополнительная проверка)
            if not response:
                response = "[Ошибка] Пустой ответ от модели"
                print(f"[HANDLE_RESPONSE] ✗ Получен пустой ответ")
            elif not isinstance(response, str):
                response = str(response) if response else "[Ошибка] Некорректный ответ"
                print(f"[HANDLE_RESPONSE] ✗ Ответ не строка, конвертирован")
            
            # Формируем историю действий (для логики, без UI)
            action_history = []
            
            # Режим AI
            if self.ai_mode == AI_MODE_FAST:
                action_history.append("[✓] быстрый режим")
            elif self.ai_mode == AI_MODE_THINKING:
                action_history.append("[✓] думающий режим")
            elif self.ai_mode == AI_MODE_PRO:
                action_history.append("[✓] про режим")
            
            # Поиск
            if hasattr(self, 'last_message_use_search') and self.last_message_use_search:
                action_history.append("[✓] найдено в интернете")
            
            # Добавляем сообщение с защитой
            # Определяем имя модели которая реально ответила (для пузыря)
            try:
                _response_model_key = (
                    self.current_worker.model_key
                    if hasattr(self, 'current_worker') and self.current_worker
                       and hasattr(self.current_worker, 'model_key')
                    else llama_handler.CURRENT_AI_MODEL_KEY
                )
                _response_speaker = llama_handler.SUPPORTED_MODELS.get(
                    _response_model_key,
                    llama_handler.SUPPORTED_MODELS.get(llama_handler.CURRENT_AI_MODEL_KEY)
                )[1]
            except Exception:
                _response_speaker = llama_handler.ASSISTANT_NAME

            # ── Обновляем виджет или создаём новый ─────────────────────────────
            _regen_widget = getattr(self, '_regen_target_widget', None)
            self._last_regen_widget = _regen_widget  # для save_message ниже
            if _regen_widget is not None:
                # Перегенерация: добавляем в историю существующего виджета
                try:
                    _regen_widget.add_regen_entry(
                        response,
                        thinking_time=thinking_time_to_show,
                        action_history=action_history,
                        sources=sources or [],
                        speaker=_response_speaker
                    )
                    print("[HANDLE_RESPONSE] ✓ Ответ добавлен в историю перегенерации виджета")
                except Exception as e:
                    print(f"[HANDLE_RESPONSE] ✗ Ошибка add_regen_entry: {e}, создаём новый виджет")
                    try:
                        self.add_message_widget(_response_speaker, response, add_controls=True, thinking_time=thinking_time_to_show, action_history=action_history, sources=sources or [])
                    except Exception as e2:
                        print(f"[HANDLE_RESPONSE] ✗ Критическая ошибка виджета: {e2}")
                finally:
                    self._regen_target_widget = None  # сбрасываем цель
            else:
                # Обычный ответ: создаём новый виджет
                try:
                    self.add_message_widget(_response_speaker, response, add_controls=True, thinking_time=thinking_time_to_show, action_history=action_history, sources=sources or [])
                except Exception as e:
                    print(f"[HANDLE_RESPONSE] ✗ Ошибка add_message_widget: {e}")
                    try:
                        # Пробуем без thinking_time
                        self.add_message_widget(_response_speaker, response, add_controls=True, thinking_time=0, action_history=action_history, sources=sources or [])
                    except Exception as e2:
                        print(f"[HANDLE_RESPONSE] ✗ Критическая ошибка виджета: {e2}")
            
            # Сохраняем в БД с защитой
            # При перегенерации — сразу передаём полную историю вариантов,
            # чтобы она была доступна при следующей загрузке чата.
            try:
                if hasattr(self, 'chat_manager') and hasattr(self, 'current_chat_id'):
                    _save_regen_hist = None
                    if _regen_widget is not None or getattr(self, '_last_regen_widget', None):
                        _target = _regen_widget if _regen_widget is not None else self._last_regen_widget
                        try:
                            _save_regen_hist = list(_target._regen_history)
                        except Exception:
                            pass
                    self.chat_manager.save_message(
                        self.current_chat_id, "assistant", response,
                        sources=sources or [],
                        speaker_name=_response_speaker,
                        regen_history=_save_regen_hist
                    )
                    if _save_regen_hist:
                        print(f"[HANDLE_RESPONSE] ✓ Сохранено с историей перегенерации ({len(_save_regen_hist)} вариантов)")
                else:
                    print(f"[HANDLE_RESPONSE] ✗ Нет chat_manager или current_chat_id")
            except Exception as e:
                print(f"[HANDLE_RESPONSE] ✗ Ошибка сохранения в БД: {e}")
            
            # Сбрасываем таймер
            self.thinking_start_time = None
            
            # ═══════════════════════════════════════════════════════════════════════════
            # ОЧИСТКА СТАТУСА ПОСЛЕ ЗАВЕРШЕНИЯ
            # ═══════════════════════════════════════════════════════════════════════════
            # ✅ ИСПРАВЛЕНИЕ: Сбрасываем status_base_text чтобы не показывать "регенерация" постоянно
            if hasattr(self, 'status_base_text'):
                self.status_base_text = ""
            
            # Плавно очищаем статус через 500ms после получения ответа
            QtCore.QTimer.singleShot(500, lambda: self.status_label.setText(""))
            print(f"[STATUS_PIPELINE] Статус будет очищен через 500ms")
            
            # Автоматическое именование чата с защитой
            try:
                messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=5)
                if messages and len(messages) == 2:
                    first_user_msg = messages[0][1] if len(messages[0]) > 1 and messages[0][0] == "user" else ""
                    if first_user_msg and isinstance(first_user_msg, str) and len(first_user_msg) > 0:
                        chat_title = first_user_msg[:40]
                        if len(first_user_msg) > 40:
                            chat_title += "..."
                        chat_title = chat_title[0].upper() + chat_title[1:] if len(chat_title) > 0 else "Новый чат"
                        self.chat_manager.update_chat_title(self.current_chat_id, chat_title)
                        self.load_chats_list()
            except Exception as e:
                print(f"[HANDLE_RESPONSE] Ошибка автоименования: {e}")
            
        except Exception as e:
            print(f"[HANDLE_RESPONSE] ✗ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # ВСЕГДА восстанавливаем UI
            try:
                self.is_generating = False  # Гарантированно сбрасываем флаг генерации
                self.send_btn.setEnabled(True)
                self.send_btn.setText("→")
                self.input_field.setEnabled(True)
                self.input_field.setFocus()
                self.activateWindow()
                self.raise_()
                # Останавливаем анимацию точек
                if hasattr(self, 'stop_status_animation'):
                    self.stop_status_animation()
            except Exception as e:
                print(f"[HANDLE_RESPONSE] Ошибка восстановления UI: {e}")


    def regenerate_last_response(self, force_model_key: str = None):
        """Перегенерировать последний ответ ассистента
        
        ЛОГИКА:
        1. Проверяем, идёт ли генерация - если да, отменяем и запускаем новую
        2. Находим последнее сообщение ассистента в UI
        3. Получаем последнее сообщение пользователя из БД
        4. Удаляем последний ответ ассистента (из UI и БД)
        5. Перезапускаем генерацию с последним запросом пользователя
        
        force_model_key — если передан, используется эта модель вместо текущей
        (для кнопки «Перегенерировать через другую модель»)
        """
        print(f"[REGENERATE] ▶ Начинаем регенерацию последнего ответа"
              + (f" (модель: {force_model_key})" if force_model_key else ""))
        
        # Если генерация идёт - останавливаем её
        if self.is_generating:
            self.is_generating = False
            if hasattr(self, 'current_worker'):
                self.current_worker = None
            print("[REGENERATE] Отменяем текущую генерацию для перезапуска")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: НАХОДИМ ПОСЛЕДНИЙ ВИДЖЕТ АССИСТЕНТА В UI
        # ═══════════════════════════════════════════════════════════════
        last_assistant_widget = None
        for i in range(self.messages_layout.count() - 1, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item and item.widget() and hasattr(item.widget(), 'speaker'):
                widget = item.widget()
                if widget.speaker != "Вы" and widget.speaker != "Система":
                    last_assistant_widget = widget
                    print(f"[REGENERATE] Найден последний виджет ассистента на позиции {i}")
                    break
        
        if not last_assistant_widget:
            print("[REGENERATE] ✗ Не найдено сообщение ассистента для регенерации")
            return
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: ПОЛУЧАЕМ ПОСЛЕДНЕЕ СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ ИЗ БД
        # ═══════════════════════════════════════════════════════════════
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=50)
        
        last_user_msg = None
        for msg_data in reversed(messages):
            role, content = msg_data[0], msg_data[1]
            if role == "user":
                last_user_msg = content
                break
        
        if not last_user_msg:
            print("[REGENERATE] ✗ Нет сообщений пользователя в текущем чате")
            return
        
        print(f"[REGENERATE] Найдено последнее сообщение пользователя: {last_user_msg[:50]}...")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: СОХРАНЯЕМ ВИДЖЕТ ДЛЯ ДОБАВЛЕНИЯ В ИСТОРИЮ
        # (НЕ удаляем — новый ответ добавится через add_regen_entry)
        # ═══════════════════════════════════════════════════════════════
        self._regen_target_widget = last_assistant_widget
        # Затемняем пузырь пока идёт генерация нового варианта
        try:
            last_assistant_widget._set_regen_dim(True)
        except Exception:
            pass
        print("[REGENERATE] ✓ Виджет сохранён как цель для истории перегенерации")
        
        # ═══════════════════════════════════════════════════════════════
        # ШАГ 4: УДАЛЯЕМ ПОСЛЕДНЕЕ СООБЩЕНИЕ АССИСТЕНТА ИЗ БД
        # ═══════════════════════════════════════════════════════════════
        conn = sqlite3.connect("chats.db")
        cur = conn.cursor()
        
        # Проверяем, что последнее сообщение - от ассистента
        cur.execute("""
            SELECT role FROM chat_messages 
            WHERE chat_id = ? 
            ORDER BY id DESC LIMIT 1
        """, (self.current_chat_id,))
        
        last_role = cur.fetchone()
        if last_role and last_role[0] == "assistant":
            cur.execute("""
                DELETE FROM chat_messages 
                WHERE chat_id = ? AND id = (
                    SELECT id FROM chat_messages 
                    WHERE chat_id = ? 
                    ORDER BY id DESC LIMIT 1
                )
            """, (self.current_chat_id, self.current_chat_id))
            conn.commit()
            print("[REGENERATE] ✓ Сообщение ассистента удалено из БД")
        else:
            print("[REGENERATE] ⚠️ Последнее сообщение в БД не от ассистента")
        
        conn.close()
        
        # Отправляем запрос заново
        self.input_field.setEnabled(False)
        self.send_btn.setText("⏸")
        self.send_btn.setEnabled(True)
        self.is_generating = True
        
        # Адаптируем deep_thinking в зависимости от режима AI (как в send_message)
        if self.ai_mode == AI_MODE_FAST:
            actual_deep_thinking = False
        elif self.ai_mode == AI_MODE_THINKING:
            actual_deep_thinking = True
        elif self.ai_mode == AI_MODE_PRO:
            actual_deep_thinking = True
        else:
            actual_deep_thinking = self.deep_thinking
        
        # Устанавливаем статус перегенерации с учётом режима
        if self.ai_mode == AI_MODE_PRO:
            self.status_base_text = "⏳ Перегенерация (режим Про)"
        elif self.ai_mode == AI_MODE_THINKING:
            self.status_base_text = "⏳ Перегенерация (режим Думающий)"
        elif self.ai_mode == AI_MODE_FAST:
            self.status_base_text = "⏳ Перегенерация (быстрый режим)"
        else:
            self.status_base_text = "⏳ Перегенерирую сообщение"
        
        self.status_label.setText(self.status_base_text)
        self.start_status_animation()
        
        # Запускаем таймер обдумывания
        self.thinking_start_time = time.time()
        
        self.current_user_message = last_user_msg

        # Поиск при регенерации: приоритет — был ли поиск при оригинальном запросе
        if hasattr(self, 'last_message_use_search') and self.last_message_use_search:
            actual_use_search = True
        elif self.use_search:
            actual_use_search = True
        else:
            ir = analyze_intent_for_search(last_user_msg, forced_search=False)
            actual_use_search = ir["requires_search"]
        self.last_message_use_search = actual_use_search
        print(f"[REGENERATE] поиск={'вкл' if actual_use_search else 'выкл'}")

        # Если передана другая модель — обновляем статус соответственно
        if force_model_key and force_model_key != llama_handler.CURRENT_AI_MODEL_KEY:
            other_display = llama_handler.SUPPORTED_MODELS.get(
                force_model_key, ("", force_model_key))[1]
            self.status_base_text = f"⏳ Перегенерация через {other_display}"
            self.status_label.setText(self.status_base_text)

        worker = AIWorker(last_user_msg, self.current_language, actual_deep_thinking,
                         actual_use_search, False, self.chat_manager, self.current_chat_id,
                         None, self.ai_mode,
                         model_key_override=force_model_key)
        worker.signals.finished.connect(self.handle_response)
        self._current_request_id = worker.request_id
        self.current_worker = worker
        
        # ✅ ИСПРАВЛЕНИЕ: Сохраняем worker в список
        self.active_workers.append(worker)
        if len(self.active_workers) > 5:
            self.active_workers = self.active_workers[-5:]
        
        self.threadpool.start(worker)
        print(f"[REGENERATE] Запущена новая генерация (модель: {force_model_key or llama_handler.CURRENT_AI_MODEL_KEY}, "
              f"режим: {self.ai_mode}, deep_thinking: {actual_deep_thinking}, search: {self.use_search})")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # STATUS PIPELINE - ПОЭТАПНОЕ ОБНОВЛЕНИЕ СТАТУСА В НИЖНЕМ ЛЕВОМ УГЛУ
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _status_pipeline_analyzing(self):
        """ЭТАП 2: Анализ запроса"""
        if not self.is_generating:
            # Генерация уже остановлена, не продолжаем pipeline
            return
        
        # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
        self.status_label.clear()
        self.status_label.setText("анализирую…")
        print(f"[STATUS_PIPELINE] Этап 2: анализирую…")
        
        # Переходим к следующему этапу в зависимости от режима
        if self.current_deep_thinking or self.current_ai_mode in [AI_MODE_THINKING, AI_MODE_PRO]:
            # Если думающий или про режим - показываем этап "думаю"
            QtCore.QTimer.singleShot(400, lambda: self._status_pipeline_thinking())
        elif self.current_use_search or self.current_ai_mode == AI_MODE_PRO:
            # Если есть поиск или про режим - переходим к поиску
            QtCore.QTimer.singleShot(400, lambda: self._status_pipeline_searching())
        else:
            # Быстрый режим без поиска - сразу к формированию ответа
            QtCore.QTimer.singleShot(400, lambda: self._status_pipeline_generating())
    
    def _status_pipeline_thinking(self):
        """ЭТАП 3: Обдумывание (только для думающего/про режима)"""
        if not self.is_generating:
            return
        
        # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
        self.status_label.clear()
        self.status_label.setText("думаю…")
        print(f"[STATUS_PIPELINE] Этап 3: думаю…")
        
        # Переходим к поиску или генерации
        if self.current_use_search or self.current_ai_mode == AI_MODE_PRO:
            QtCore.QTimer.singleShot(600, lambda: self._status_pipeline_searching())
        else:
            QtCore.QTimer.singleShot(600, lambda: self._status_pipeline_generating())
    
    def _status_pipeline_searching(self):
        """ЭТАП 4: Поиск информации (если активирован поиск или про режим)"""
        if not self.is_generating:
            return
        
        # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
        self.status_label.clear()
        self.status_label.setText("ищу информацию…")
        print(f"[STATUS_PIPELINE] Этап 4: ищу информацию…")
        
        # Переходим к формированию ответа
        QtCore.QTimer.singleShot(800, lambda: self._status_pipeline_generating())
    
    def _status_pipeline_generating(self):
        """ЭТАП 5: Формирование ответа"""
        if not self.is_generating:
            return
        
        # ✅ КРИТИЧНО: Очищаем перед установкой нового текста
        self.status_label.clear()
        self.status_label.setText("формирую ответ…")
        print(f"[STATUS_PIPELINE] Этап 5: формирую ответ…")
        
        # После завершения статус будет очищен в handle_response
    
    def edit_last_message(self, old_text=None):
        """Редактировать последнее сообщение пользователя
        
        ЛОГИКА:
        1. Получить последний user-запрос из текущего чата
        2. Вернуть текст в поле ввода
        3. Удалить последние 2 сообщения (user + assistant) + ActionIndicatorRow из UI и БД
        4. Установить флаг режима редактирования
        5. При отправке сообщение заменится, а не добавится
        """
        if self.is_generating:
            print("[EDIT] ✗ Генерация идёт, редактирование невозможно")
            return
        
        # Получаем последнее сообщение пользователя из ТЕКУЩЕГО чата
        messages = self.chat_manager.get_chat_messages(self.current_chat_id, limit=50)
        
        last_user_msg = None
        for msg_data in reversed(messages):
            role, content = msg_data[0], msg_data[1]
            if role == "user":
                last_user_msg = content
                break
        
        if not last_user_msg:
            print("[EDIT] ✗ Нет сообщений пользователя для редактирования")
            return
        
        print(f"[EDIT] Редактируем последний запрос: {last_user_msg[:50]}...")
        
        # Удаляем последние 2 виджета (user + assistant)
        removed_count = 0
        while self.messages_layout.count() > 1 and removed_count < 2:
            last_item = self.messages_layout.itemAt(self.messages_layout.count() - 2)
            if last_item and last_item.widget():
                last_item.widget().deleteLater()
                removed_count += 1
        
        print(f"[EDIT] ✓ Удалено виджетов: {removed_count}")
        
        # Удаляем последние 2 сообщения из БД текущего чата
        conn = sqlite3.connect("chats.db")
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM chat_messages 
            WHERE chat_id = ? AND id IN (
                SELECT id FROM chat_messages 
                WHERE chat_id = ? 
                ORDER BY id DESC LIMIT 2
            )
        """, (self.current_chat_id, self.current_chat_id))
        conn.commit()
        conn.close()
        print("[EDIT] ✓ Удалены последние 2 сообщения из БД")
        
        # УСТАНАВЛИВАЕМ РЕЖИМ РЕДАКТИРОВАНИЯ
        self.is_editing = True
        self.editing_message_text = last_user_msg
        
        # ВОССТАНАВЛИВАЕМ РЕЖИМЫ которые были при отправке сообщения
        if hasattr(self, 'last_message_deep_thinking') and hasattr(self, 'last_message_use_search'):
            self.deep_thinking = self.last_message_deep_thinking
            self.use_search = self.last_message_use_search
            self.think_toggle.setChecked(self.deep_thinking)
            self.search_toggle.setChecked(self.use_search)
            print(f"[EDIT] Восстановлены режимы: думать={self.deep_thinking}, поиск={self.use_search}")
        else:
            print(f"[EDIT] Текущие режимы: думать={self.deep_thinking}, поиск={self.use_search}")
        
        # ВОЗВРАЩАЕМ ТЕКСТ В ПОЛЕ ВВОДА И УСТАНАВЛИВАЕМ КУРСОР В КОНЕЦ
        self.input_field.setText(last_user_msg)
        self.input_field.setEnabled(True)
        self.input_field.setFocus()
        self.input_field.setCursorPosition(len(last_user_msg))
        print(f"[EDIT] ✓ Режим редактирования активирован")

    def clear_chat(self):
        """Очистка чата с кастомным окном подтверждения"""
        print("[CLEAR_CHAT] Метод вызван!")
        
        # Блокируем очистку если идёт генерация
        if self.is_generating:
            print("[CLEAR_CHAT] Генерация в процессе - очистка заблокирована")
            return
        
        # Проверяем, есть ли сообщения в чате (кроме системных)
        messages_count = 0
        for i in range(self.messages_layout.count() - 1):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'speaker') and widget.speaker != "Система":
                    messages_count += 1
        
        print(f"[CLEAR_CHAT] Найдено сообщений: {messages_count}")
        
        if messages_count == 0:
            print("[CLEAR_CHAT] Нет сообщений - выход")
            return
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Создаём МОДАЛЬНОЕ окно (работает на Mac)
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("")
        dialog.setModal(True)
        dialog.setFixedSize(420, 220)
        
        # Убираем рамку окна
        dialog.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Dialog)
        # Прозрачность работает плохо на Windows
        if not IS_WINDOWS:
            dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Центрируем по ЭКРАНУ (не по родителю)
        screen_geo = QtWidgets.QApplication.primaryScreen().geometry()
        dialog.move(
            screen_geo.center().x() - 210,
            screen_geo.center().y() - 110
        )
        
        # Layout
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Стеклянный контейнер с адаптацией под тему
        frame = QtWidgets.QFrame()
        
        # КРИТИЧНО: Устанавливаем что фон НЕ должен рисоваться поверх дочерних элементов
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        
        if is_dark:
            # Тёмная тема - стеклянный фон БЕЗ дополнительных слоёв
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(30, 30, 35, 0.92);
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 20px;
                }
            """)
        else:
            # Светлая тема - стеклянный фон БЕЗ дополнительных слоёв
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(255, 255, 255, 0.90);
                    border: 1px solid rgba(255, 255, 255, 0.95);
                    border-radius: 20px;
                }
            """)
        
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(35, 35, 35, 35)
        frame_layout.setSpacing(28)
        
        # Текст - КРИТИЧНО: убираем любые стили которые могут создать слой
        label = QtWidgets.QLabel("Вы уверены, что хотите\nочистить чат?")
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setFont(_apple_font(16, weight=QtGui.QFont.Weight.Medium))
        
        # ИСПРАВЛЕНИЕ: Минимальный стиль только для цвета текста
        # НЕ используем padding, background и другие свойства которые создают слои
        if is_dark:
            label.setStyleSheet("QLabel { color: #e6e6e6; background-color: none; border: none; }")
        else:
            label.setStyleSheet("QLabel { color: #2d3748; background-color: none; border: none; }")
        
        label.setWordWrap(True)
        
        # КРИТИЧНО: Поднимаем label поверх всех слоёв
        label.raise_()
        
        frame_layout.addWidget(label)
        
        # Кнопки
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(15)
        
        no_btn = QtWidgets.QPushButton("НЕТ")
        no_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Bold))
        no_btn.setFixedHeight(54)
        no_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        if is_dark:
            no_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(60, 60, 70, 0.7);
                    color: #c0c0c0;
                    border: 1px solid rgba(80, 80, 90, 0.8);
                    border-radius: 13px;
                    padding: 8px 18px;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(70, 70, 80, 0.85);
                    border: 1px solid rgba(90, 90, 100, 0.9);
                }
            """)
        else:
            no_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(200, 200, 200, 0.6);
                    color: #4a5568;
                    border: 1px solid rgba(200, 200, 200, 0.75);
                    border-radius: 13px;
                    padding: 8px 18px;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(200, 200, 200, 0.8);
                }
            """)
        
        yes_btn = QtWidgets.QPushButton("ДА")
        yes_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Bold))
        yes_btn.setFixedHeight(54)
        yes_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        if is_dark:
            yes_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(220, 38, 38, 0.95);
                    color: #ffffff;
                    border: 1px solid rgba(220, 38, 38, 1.0);
                    border-radius: 13px;
                    padding: 8px 18px;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(185, 28, 28, 1.0);
                    border: 1px solid rgba(185, 28, 28, 1.0);
                }
            """)
        else:
            yes_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(239, 68, 68, 0.95);
                    color: white;
                    border: none;
                    border-radius: 13px;
                    padding: 8px 18px;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(220, 38, 38, 1.0);
                }
            """)
        
        buttons.addWidget(no_btn)
        buttons.addWidget(yes_btn)
        
        # КРИТИЧНО: Поднимаем кнопки поверх всех слоёв
        no_btn.raise_()
        yes_btn.raise_()
        
        frame_layout.addLayout(buttons)
        
        layout.addWidget(frame)
        
        # Обработчики с плавным закрытием
        def _close_dialog_animated(accept: bool):
            """Плавное закрытие: fade-out, затем закрытие"""
            # Отключаем кнопки чтобы не нажали дважды
            no_btn.setEnabled(False)
            yes_btn.setEnabled(False)

            _d_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
            dialog.setGraphicsEffect(_d_eff)
            _d_eff.setOpacity(1.0)

            _d_op = QtCore.QPropertyAnimation(_d_eff, b"opacity")
            _d_op.setDuration(160)
            _d_op.setStartValue(1.0)
            _d_op.setEndValue(0.0)
            _d_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            def _finish():
                if accept:
                    dialog.accept()
                else:
                    dialog.reject()

            _d_op.finished.connect(_finish)
            _d_op.start()
            dialog._close_anims = [_d_op, _d_eff]

        no_btn.clicked.connect(lambda: _close_dialog_animated(False))
        yes_btn.clicked.connect(lambda: _close_dialog_animated(True))

        print("[CLEAR_CHAT] Показываю диалог...")

        # Плавное открытие: только fade-in (без geometry — избегаем сдвигов)
        _open_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
        dialog.setGraphicsEffect(_open_eff)
        _open_eff.setOpacity(0.0)

        _open_op = QtCore.QPropertyAnimation(_open_eff, b"opacity")
        _open_op.setDuration(220)
        _open_op.setStartValue(0.0)
        _open_op.setEndValue(1.0)
        _open_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        def _on_open_done():
            try:
                dialog.setGraphicsEffect(None)
            except Exception:
                pass

        _open_op.finished.connect(_on_open_done)
        _open_op.start()
        dialog._open_anims = [_open_op, _open_eff]

        result = dialog.exec()
        
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            print("[CLEAR_CHAT] Пользователь подтвердил очистку")
            self.perform_clear_chat()
        else:
            print("[CLEAR_CHAT] Пользователь отменил очистку")
    
    def perform_clear_chat(self):
        """Выполнить очистку чата с плавной iOS-style анимацией"""
        print("[PERFORM_CLEAR] Начинаем плавную очистку...")
        
        # Собираем все виджеты сообщений для удаления
        widgets = []
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                # Удаляем все виджеты сообщений
                if hasattr(widget, 'speaker'):
                    widgets.append(widget)
        
        print(f"[PERFORM_CLEAR] Виджетов для удаления: {len(widgets)}")
        
        if len(widgets) == 0:
            print("[PERFORM_CLEAR] Нет виджетов для удаления")
            self.finalize_clear()
            return
        
        # Блокируем UI во время анимации
        self.input_field.setEnabled(False)
        self.send_btn.setEnabled(False)
        
        # ПЛАВНАЯ iOS-style анимация для ВСЕХ платформ
        # Удаляем сообщения снизу вверх с небольшой задержкой
        total_duration = 0
        for idx, widget in enumerate(reversed(widgets)):  # Снизу вверх
            delay = idx * 40  # Меньше задержка = быстрее
            total_duration = delay + 300  # 300ms на саму анимацию
            QtCore.QTimer.singleShot(delay, lambda w=widget: self.smooth_fade_and_remove(w))
        
        # После завершения всех анимаций - финализируем
        QtCore.QTimer.singleShot(total_duration + 100, self.finalize_clear)
    
    def smooth_fade_and_remove(self, widget):
        """
        Плавное удаление виджета через fade-out анимацию.
        
        ВАЖНО: Только fade-out прозрачности, БЕЗ изменения размеров.
        После удаления виджета layout автоматически пересчитывается.
        """
        try:
            if not widget or not widget.isVisible():
                return
            
            # Создаём эффект прозрачности если его нет
            if not widget.graphicsEffect():
                opacity_effect = QtWidgets.QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(opacity_effect)
            else:
                opacity_effect = widget.graphicsEffect()
            
            # Fade-out анимация
            fade_anim = QtCore.QPropertyAnimation(opacity_effect, b"opacity")
            fade_anim.setDuration(300)
            fade_anim.setStartValue(1.0)
            fade_anim.setEndValue(0.0)
            fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            
            # Удаляем виджет после завершения анимации
            def cleanup():
                try:
                    # КРИТИЧНО: Сначала останавливаем анимацию
                    if hasattr(widget, '_cleanup_anim'):
                        widget._cleanup_anim.stop()
                        widget._cleanup_anim = None
                    
                    # Затем удаляем эффект
                    if widget.graphicsEffect():
                        widget.setGraphicsEffect(None)
                    
                    # Удаляем ссылку на эффект
                    if hasattr(widget, '_opacity_effect'):
                        widget._opacity_effect = None
                    
                    # И только после этого удаляем виджет
                    self.messages_layout.removeWidget(widget)
                    widget.deleteLater()
                    # Layout обновится автоматически
                except RuntimeError:
                    # Объект уже удалён - игнорируем
                    pass
                except Exception as e:
                    print(f"[CLEANUP] Ошибка при удалении виджета: {e}")
            
            fade_anim.finished.connect(cleanup)
            fade_anim.start()
            
            # Сохраняем ссылку на анимацию И на эффект прозрачности
            widget._cleanup_anim = fade_anim
            widget._opacity_effect = opacity_effect
            
        except Exception as e:
            print(f"[SMOOTH_FADE] Ошибка: {e}")
            # В случае ошибки - просто удаляем виджет
            try:
                if widget.graphicsEffect():
                    widget.setGraphicsEffect(None)
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
                # Layout обновится автоматически
            except RuntimeError:
                pass
    
    
    def finalize_clear(self):
        """Завершение очистки чата после анимации"""
        try:
            print("[FINALIZE] Очищаем БД и восстанавливаем UI...")
            
            # ✅ Удаляем все оставшиеся виджеты сообщений (на случай если анимация не завершилась)
            # Оставляем только stretch в конце
            items_to_remove = []
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    # Удаляем только виджеты с атрибутом speaker (сообщения)
                    if hasattr(widget, 'speaker'):
                        items_to_remove.append(widget)
            
            for widget in items_to_remove:
                self.messages_layout.removeWidget(widget)
                widget.deleteLater()
            
            print(f"[FINALIZE] Удалено оставшихся виджетов: {len(items_to_remove)}")
            
            # Очищаем БД сообщений И контекстную память чата
            self.chat_manager.clear_chat_messages(self.current_chat_id)
            try:
                from context_memory_manager import ContextMemoryManager
                ContextMemoryManager().clear_context_memory(self.current_chat_id)
                print(f"[FINALIZE] ✓ Контекстная память LLaMA чата {self.current_chat_id} очищена")
            except Exception as e:
                print(f"[FINALIZE] ⚠️ Ошибка очистки контекстной памяти: {e}")
            try:
                if DeepSeekMemoryManager is not None:
                    _DS_MEMORY.clear_context_memory(self.current_chat_id)
                    print(f"[FINALIZE] ✓ Память DeepSeek чата {self.current_chat_id} очищена")
            except Exception as e:
                print(f"[FINALIZE] ⚠️ Ошибка очистки памяти DeepSeek: {e}")
            self.chat_manager.update_chat_title(self.current_chat_id, "Новый чат")
            self.load_chats_list()
            
            # Добавляем системное сообщение (автоскролл произойдет автоматически)
            self.add_message_widget("Система", "Чат очищен", add_controls=False)
            
            # Восстанавливаем UI
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.input_field.setFocus()
            
            print("[FINALIZE] Готово!")
        except Exception as e:
            print(f"[FINALIZE] Ошибка: {e}")
            import traceback
            traceback.print_exc()
            # В случае ошибки - всё равно восстанавливаем UI
            self.input_field.setEnabled(True)
            self.send_btn.setEnabled(True)
    
    def confirm_delete_all_chats(self):
        """Показать диалог подтверждения удаления ВСЕХ чатов"""
        print("[DELETE_ALL_CHATS] Запрос подтверждения удаления всех чатов")
        
        # Получаем текущую тему
        is_dark = self.current_theme == "dark"
        
        # Создаём модальное окно
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("")
        dialog.setModal(True)
        dialog.setFixedSize(450, 210)
        
        # Убираем рамку окна и поднимаем поверх всего
        dialog.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.Dialog |
            QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        if not IS_WINDOWS:
            dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Центрируем по экрану
        screen_geo = QtWidgets.QApplication.primaryScreen().geometry()
        dialog.move(
            screen_geo.center().x() - 225,
            screen_geo.center().y() - 110
        )
        
        # Layout без отступов — frame полностью заполняет диалог (нет прозрачных краёв)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Стеклянный контейнер
        frame = QtWidgets.QFrame()
        frame.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        
        if is_dark:
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(30, 30, 35, 0.97);
                    border: 1px solid rgba(60, 60, 70, 0.8);
                    border-radius: 20px;
                }
            """)
        else:
            frame.setStyleSheet("""
                QFrame {
                    background-color: rgba(255, 255, 255, 0.97);
                    border: 1px solid rgba(200, 200, 210, 0.9);
                    border-radius: 20px;
                }
            """)
        
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(30, 24, 30, 24)
        frame_layout.setSpacing(0)
        
        # Заголовок
        title = QtWidgets.QLabel("⚠️ Удалить все чаты?")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setFont(_apple_font(18, weight=QtGui.QFont.Weight.Bold))
        
        if is_dark:
            title.setStyleSheet("QLabel { color: #e89999; background-color: none; border: none; }")
        else:
            title.setStyleSheet("QLabel { color: #c85555; background-color: none; border: none; }")
        
        frame_layout.addWidget(title)
        frame_layout.addSpacing(14)
        
        # Текст предупреждения
        warning = QtWidgets.QLabel("Это действие невозможно отменить.\nВсе чаты будут удалены безвозвратно.")
        warning.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        warning.setFont(_apple_font(13, weight=QtGui.QFont.Weight.Normal))
        warning.setWordWrap(True)
        
        if is_dark:
            warning.setStyleSheet("QLabel { color: #b0b0b0; background-color: none; border: none; }")
        else:
            warning.setStyleSheet("QLabel { color: #64748b; background-color: none; border: none; }")
        
        frame_layout.addWidget(warning)
        frame_layout.addSpacing(14)
        
        # Кнопки
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(15)
        
        no_btn = QtWidgets.QPushButton("Отмена")
        no_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Medium))
        no_btn.setMinimumHeight(48)
        no_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        if is_dark:
            no_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(60, 60, 70, 0.70);
                    color: #e6e6e6;
                    border: none;
                    border-radius: 13px;
                    padding: 8px 18px;
                }
                QPushButton:hover {
                    background: rgba(70, 70, 80, 0.85);
                }
            """)
        else:
            no_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(226, 232, 240, 0.90);
                    color: #334155;
                    border: none;
                    border-radius: 13px;
                    padding: 8px 18px;
                }
                QPushButton:hover {
                    background: rgba(203, 213, 225, 1.0);
                }
            """)
        
        yes_btn = QtWidgets.QPushButton("Удалить все")
        yes_btn.setFont(_apple_font(14, weight=QtGui.QFont.Weight.Bold))
        yes_btn.setMinimumHeight(48)
        yes_btn.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        yes_btn.setStyleSheet("""
            QPushButton {
                background: rgba(239, 68, 68, 0.95);
                color: white;
                border: none;
                border-radius: 13px;
                padding: 8px 18px;
                text-align: center;
            }
            QPushButton:hover {
                background: rgba(220, 38, 38, 1.0);
            }
        """)
        
        buttons.addWidget(no_btn)
        buttons.addWidget(yes_btn)
        
        no_btn.raise_()
        yes_btn.raise_()
        
        frame_layout.addLayout(buttons)
        layout.addWidget(frame)
        
        # Обработчики с плавным закрытием
        def _close_delete_animated(accept: bool):
            no_btn.setEnabled(False)
            yes_btn.setEnabled(False)

            _d_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
            dialog.setGraphicsEffect(_d_eff)
            _d_eff.setOpacity(1.0)

            _d_op = QtCore.QPropertyAnimation(_d_eff, b"opacity")
            _d_op.setDuration(160)
            _d_op.setStartValue(1.0)
            _d_op.setEndValue(0.0)
            _d_op.setEasingCurve(QtCore.QEasingCurve.Type.InCubic)

            def _finish():
                if accept:
                    dialog.accept()
                else:
                    dialog.reject()

            _d_op.finished.connect(_finish)
            _d_op.start()
            dialog._close_anims = [_d_op, _d_eff]

        no_btn.clicked.connect(lambda: _close_delete_animated(False))
        yes_btn.clicked.connect(lambda: _close_delete_animated(True))

        print("[DELETE_ALL_CHATS] Показываю диалог...")
        dialog.raise_()
        dialog.activateWindow()

        # Плавное открытие: только fade-in (без geometry — избегаем сдвигов)
        _open_eff = QtWidgets.QGraphicsOpacityEffect(dialog)
        dialog.setGraphicsEffect(_open_eff)
        _open_eff.setOpacity(0.0)

        _open_op = QtCore.QPropertyAnimation(_open_eff, b"opacity")
        _open_op.setDuration(220)
        _open_op.setStartValue(0.0)
        _open_op.setEndValue(1.0)
        _open_op.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        def _on_open_done():
            try:
                dialog.setGraphicsEffect(None)
            except Exception:
                pass

        _open_op.finished.connect(_on_open_done)
        _open_op.start()
        dialog._open_anims = [_open_op, _open_eff]

        result = dialog.exec()
        
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            print("[DELETE_ALL_CHATS] Пользователь подтвердил удаление всех чатов")
            self.perform_delete_all_chats()
        else:
            print("[DELETE_ALL_CHATS] Пользователь отменил удаление")
    
    def perform_delete_all_chats(self):
        """Удалить все чаты и создать новый — напрямую через SQL"""
        print("[DELETE_ALL_CHATS] ▶ Начинаю полное удаление...")
        
        try:
            import sqlite3 as _sqlite3
            
            # ШАГ 0: Очищаем ВСЮ контекстную память ПЕРЕД удалением чатов
            try:
                from context_memory_manager import ContextMemoryManager
                ContextMemoryManager().clear_all_context()
                print("[DELETE_ALL_CHATS] ✓ Вся контекстная память LLaMA очищена")
            except Exception as e:
                print(f"[DELETE_ALL_CHATS] ⚠️ Ошибка очистки контекстной памяти: {e}")
            try:
                if DeepSeekMemoryManager is not None:
                    _DS_MEMORY.clear_all_context()
                    print("[DELETE_ALL_CHATS] ✓ Вся память DeepSeek очищена")
            except Exception as e:
                print(f"[DELETE_ALL_CHATS] ⚠️ Ошибка очистки памяти DeepSeek: {e}")

            # ШАГ 1: Напрямую чистим БД — гарантированно удаляем всё
            # Берём путь из модуля chat_manager
            import chat_manager as _cm_module
            db_path = _cm_module.CHATS_DB
            conn = _sqlite3.connect(db_path)
            cur = conn.cursor()
            
            cur.execute("DELETE FROM chat_messages")
            cur.execute("DELETE FROM chats")
            
            # Сбрасываем автоинкремент
            cur.execute("DELETE FROM sqlite_sequence WHERE name='chats'")
            cur.execute("DELETE FROM sqlite_sequence WHERE name='chat_messages'")
            
            # Создаём один чистый чат
            from datetime import datetime as _dt
            now = _dt.utcnow().isoformat()
            cur.execute(
                "INSERT INTO chats (title, created_at, updated_at, is_active) VALUES (?, ?, ?, ?)",
                ("Новый чат", now, now, 1)
            )
            new_chat_id = cur.lastrowid
            conn.commit()
            conn.close()
            
            print(f"[DELETE_ALL_CHATS] ✓ БД очищена. Новый чат ID={new_chat_id}")
            
            # ШАГ 2: Обновляем все внутренние ID
            self.current_chat_id = new_chat_id
            self.startup_chat_id = new_chat_id
            if _DS_MEMORY is not None:
                _DS_MEMORY.on_chat_switch(new_chat_id)
            
            # ШАГ 3: Если в настройках — возвращаемся к чату плавно
            if self.content_stack.currentIndex() == 1:
                self._animate_stack_transition(from_index=1, to_index=0,
                                               callback=self._after_close_settings)
                QtWidgets.QApplication.processEvents()
            
            # ШАГ 4: Очищаем виджеты сообщений
            to_remove = []
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item and item.widget() and hasattr(item.widget(), 'speaker'):
                    to_remove.append(item.widget())
            for w in to_remove:
                self.messages_layout.removeWidget(w)
                w.deleteLater()
            print(f"[DELETE_ALL_CHATS] ✓ Удалено виджетов: {len(to_remove)}")
            
            # ШАГ 5: Обновляем список чатов в сайдбаре
            self.chats_list.clear()
            chats = self.chat_manager.get_all_chats()
            print(f"[DELETE_ALL_CHATS] Чатов в БД после удаления: {len(chats)}")
            for chat in chats:
                item = QtWidgets.QListWidgetItem(chat['title'])
                item.setData(QtCore.Qt.ItemDataRole.UserRole, chat['id'])
                self.chats_list.addItem(item)
                if chat['is_active']:
                    self.chats_list.setCurrentItem(item)
            self.chats_list.repaint()
            
            # ШАГ 6: Показываем приветствие
            self.add_message_widget("Система", "Привет! Готов к работе.", add_controls=False)
            
            # ШАГ 7: Скроллим вниз
            QtCore.QTimer.singleShot(100, lambda: self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().maximum()
            ))
            
            print("[DELETE_ALL_CHATS] ✓ Всё готово!")
            
        except Exception as e:
            print(f"[DELETE_ALL_CHATS] ✗ Ошибка: {e}")
            import traceback
            traceback.print_exc()


    # ═══════════════════════════════════════════════════════════════
    # DRAG-AND-DROP: Обработка перетаскивания файлов
    # ═══════════════════════════════════════════════════════════════
    

def main():
    """Главная функция запуска с полной диагностикой и самовосстановлением."""

    # ── Шаг 1: базовая инициализация Qt (нужна раньше всего для диалогов) ──
    try:
        app = QtWidgets.QApplication(sys.argv)
    except Exception as e:
        print(f"[MAIN] ❌ Не удалось создать QApplication: {e}")
        sys.exit(1)

    if IS_WINDOWS:
        app.setStyle("Fusion")
        # ── Apple-style рендеринг шрифтов на Windows ──────────────────────
        # QtGui уже импортирован глобально — НЕ импортируем повторно (UnboundLocalError)
        _win_font = next(
            (n for n in ["Segoe UI Variable", "Segoe UI"] if n in QtGui.QFontDatabase.families()),
            "Segoe UI"
        )
        _gf = QtGui.QFont(_win_font, 11)
        _gf.setHintingPreference(QtGui.QFont.HintingPreference.PreferNoHinting)
        _gf.setStyleStrategy(
            QtGui.QFont.StyleStrategy.PreferAntialias |
            QtGui.QFont.StyleStrategy.PreferQuality
        )
        app.setFont(_gf)
        import os; os.environ.setdefault("QT_FONT_DPI", "96")
        print(f"[FONT] ✓ Apple-style: {_win_font}, субпиксельный рендеринг")

    # ── Шаг 1.5: запуск Ollama ────────────────────────────────────────────────
    # Ищем бинарник во ВСЕХ стандартных местах ОС и сразу запускаем в фоне.
    # Не блокируем главный поток — просто стартуем и идём дальше.
    # Если Ollama не найдена — диалог откроется после запуска главного окна.
    print("[MAIN] Проверка Ollama…")
    try:
        import threading as _thr0
        from ollama_manager import is_ollama_running, find_ollama_binary, launch_ollama

        if is_ollama_running():
            print("[MAIN] ✅ Ollama уже запущена")
        else:
            _binary = find_ollama_binary()
            if _binary:
                print(f"[MAIN] Найдена Ollama: {_binary} — запускаем в фоне")
                # launch_ollama запускает процесс (не блокирует), ждать не нужно
                _thr0.Thread(target=launch_ollama, args=(_binary,), daemon=True).start()
            else:
                print("[MAIN] Ollama не найдена в стандартных местах — диалог после окна")
    except Exception as _oe:
        print(f"[MAIN] ⚠️ ollama_manager: {_oe}")
    print("[MAIN] Запуск диагностики...")
    report = startup_checks(
        check_ollama   = False,  # Ollama управляется через ollama_manager
        check_dbs      = ["chats.db", "chat_memory.db", "deepseek_memory.db"],
        check_packages = True,
        check_space    = True,
        check_files    = True,
        check_settings = True,
        auto_fix       = True,
        qt_app         = app,
    )

    # ── Шаг 3: фатальные ошибки — показываем и выходим ────────────────────
    if report["fatal"]:
        error_msg = build_fatal_error_message(report)
        QtWidgets.QMessageBox.critical(
            None,
            "❌ Ошибка запуска",
            error_msg,
            QtWidgets.QMessageBox.StandardButton.Ok,
        )
        sys.exit(1)

    # ── Шаг 4: предупреждения — показываем и продолжаем ───────────────────
    if report["warnings"]:
        ollama_warns = [w for w in report["warnings"] if "ollama" in w.lower()]
        other_warns  = [w for w in report["warnings"] if "ollama" not in w.lower()]
        if other_warns:
            detail = "\n".join(other_warns)
            QtWidgets.QMessageBox.warning(
                None,
                "⚠️ Предупреждения при запуске",
                f"Приложение запущено с предупреждениями:\n\n{detail}\n\n"
                "Программа продолжит работу, но некоторые функции могут быть ограничены.",
                QtWidgets.QMessageBox.StandardButton.Ok,
            )

    # ── Шаг 5: инициализация БД приложения ────────────────────────────────
    try:
        print("[MAIN] Инициализация базы данных...")
        init_db()

        print("[MAIN] Запуск миграции ChatManager...")
        from chat_manager import ChatManager
        chat_mgr = ChatManager()
        print("[MAIN] ✓ База данных готова")
    except Exception as e:
        log_error("MAIN_DB_INIT", e)
        QtWidgets.QMessageBox.critical(
            None,
            "❌ Ошибка БД",
            f"Не удалось инициализировать базу данных:\n{e}\n\n"
            "Попробуйте удалить файлы .db и перезапустить программу.",
            QtWidgets.QMessageBox.StandardButton.Ok,
        )
        sys.exit(1)

    # ── Шаг 6: создаём главное окно ───────────────────────────────────────
    try:
        print("[MAIN] Создание иконки приложения...")
        app_icon = create_app_icon()
        app.setWindowIcon(QtGui.QIcon(app_icon))

        print("[MAIN] Создание главного окна...")
        window = MainWindow()
        window.show()

        # ── Цепочка запуска Ollama ────────────────────────────────────────────
        # Правильный Qt-паттерн: сигналы из фонового потока → слоты в главном.
        # QTimer.singleShot из фонового потока ненадёжен — функция может быть
        # собрана GC до срабатывания. Сигналы Qt гарантируют доставку.

        class _OllamaBridge(QtCore.QObject):
            """Мост: фоновый поток → главный поток через Qt-сигналы."""
            ollama_ready   = QtCore.pyqtSignal()   # Ollama запущена → проверить модели
            need_install   = QtCore.pyqtSignal()   # Ollama не найдена → диалог установки

        _bridge = _OllamaBridge()

        def _after_ollama_ready():
            """Ollama запущена (или не найдена — неважно). Проверяем модели."""
            print("[MAIN] → _check_first_launch()")
            window._check_first_launch()

        def _show_ollama_install_dialog():
            """Показывает диалог установки Ollama. Вызывается в главном потоке."""
            print("[MAIN] Открываем OllamaDownloadDialog...")
            try:
                from model_downloader import OllamaDownloadDialog
                dlg = OllamaDownloadDialog(window)
                accepted = dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted
                if accepted:
                    print("[MAIN] Пользователь принял установку — ищем бинарник...")
                    # После установки запускаем в фоне, потом проверяем модели
                    def _after_install():
                        try:
                            from ollama_manager import find_ollama_binary, launch_ollama, wait_for_ollama
                            binary = find_ollama_binary()
                            if binary:
                                launch_ollama(binary)
                                print("[MAIN] ✅ Ollama установлена и запущена")
                            else:
                                print("[MAIN] ⚠️ После установки бинарник не найден")
                        except Exception as _e:
                            print(f"[MAIN] ⚠️ _after_install: {_e}")
                        finally:
                            _bridge.ollama_ready.emit()
                    import threading as _thr2
                    _thr2.Thread(target=_after_install, daemon=True).start()
                else:
                    print("[MAIN] Пользователь отказался от установки Ollama")
                    # Не предлагаем модели — Ollama не установлена, смысла нет
            except Exception as _e:
                print(f"[MAIN] ⚠️ OllamaDownloadDialog: {_e}")

        # Подключаем сигналы к слотам (всё в главном потоке)
        _bridge.ollama_ready.connect(_after_ollama_ready)
        _bridge.need_install.connect(_show_ollama_install_dialog)

        def _ollama_startup_check():
            """
            Фоновый поток: проверяет/ищет/запускает Ollama.
            Общается с главным потоком ТОЛЬКО через сигналы _bridge.
            """
            try:
                from ollama_manager import is_ollama_running, find_ollama_binary, launch_ollama
                print("[MAIN] Проверяем Ollama...")

                if is_ollama_running():
                    print("[MAIN] ✅ Ollama уже запущена")
                    _bridge.ollama_ready.emit()
                    return

                binary = find_ollama_binary()
                if binary:
                    print(f"[MAIN] Бинарник найден: {binary} — запускаем")
                    launch_ollama(binary)
                    print("[MAIN] ✅ Ollama запущена в фоне")
                    _bridge.ollama_ready.emit()
                else:
                    print("[MAIN] ❌ Ollama не найдена — сигнал диалога установки")
                    _bridge.need_install.emit()

            except Exception as _e:
                print(f"[MAIN] ⚠️ _ollama_startup_check: {_e}")
                # При ошибке всё равно проверяем модели
                _bridge.ollama_ready.emit()

        import threading as _thr_ol
        _thr_ol.Thread(target=_ollama_startup_check, daemon=True).start()

        print("[MAIN] ✅ Запуск главного цикла...")
        sys.exit(app.exec())

    except Exception as e:
        log_error("MAIN_WINDOW", e)
        QtWidgets.QMessageBox.critical(
            None,
            "❌ Ошибка запуска",
            f"Не удалось создать главное окно:\n\n{e}\n\n"
            "Проверьте файл errors.log для подробностей.",
            QtWidgets.QMessageBox.StandardButton.Ok,
        )
        sys.exit(1)

if __name__ == "__main__":
    main()